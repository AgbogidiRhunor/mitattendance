"""Application admin pages (superusers and sub admins)."""
import csv

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import roles
from accounts.models import SUB_ADMIN_GROUP, USHER_GROUP, User

from .decorators import admin_required
from .forms import CorrectionForm, DateRangeForm, SessionForm
from .models import AttendanceAuditLog, AttendanceRecord, MeetingSession
from .services import (AttendanceError, close_session_now, correct_attendance, delete_attendance,
                       delete_session, finalize_session)
from .stats import annotate_counts, history_qs, period_totals, pct, session_rows, user_stats
from .utils import paginate, search_users

Status = MeetingSession.Status


def _csv_safe(value):
    """Neutralise spreadsheet formula injection from user-supplied text."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_safe(c) for c in row])
    return response


@admin_required
def dashboard(request):
    MeetingSession.sync_statuses()
    form = DateRangeForm(request.GET or None)
    finalized = form.apply(MeetingSession.objects.filter(status=Status.FINALIZED))
    totals = period_totals(finalized)
    rows = session_rows(annotate_counts(finalized).order_by("-meeting_date", "-opens_at")[:10])
    return render(request, "meetings/manage/dashboard.html", {
        "form": form, "totals": totals, "rows": rows,
        "total_users": User.objects.filter(is_active=True).count(),
        "open_sessions": MeetingSession.open_now().count(),
        "qs": request.GET.urlencode(),
    })


@admin_required
def report_csv(request):
    form = DateRangeForm(request.GET or None)
    qs = form.apply(MeetingSession.objects.filter(status=Status.FINALIZED))
    rows = session_rows(annotate_counts(qs).order_by("meeting_date"))
    return _csv_response("attendance_report.csv",
                         ["Title", "Date", "Eligible", "Attendees", "Absent", "Attendance %"],
                         [[r["session"].title, r["session"].meeting_date, r["eligible"], r["attendees"],
                           r["absent"], r["percent"] if r["percent"] is not None else ""] for r in rows])


@admin_required
def sessions(request):
    MeetingSession.sync_statuses()
    qs = MeetingSession.objects.all()
    status = request.GET.get("status", "")
    if status in Status.values:
        qs = qs.filter(status=status)
    page_obj, query = paginate(request, annotate_counts(qs).order_by("-meeting_date", "-opens_at"))
    page_obj.object_list = session_rows(page_obj.object_list)
    return render(request, "meetings/manage/sessions.html", {
        "page_obj": page_obj, "qs": query, "status": status, "statuses": Status.choices})


@admin_required
def session_create(request):
    local_now = timezone.localtime().replace(second=0, microsecond=0)
    form = SessionForm(request.POST or None, initial={"meeting_date": local_now.date(), "opens_at": local_now})
    if request.method == "POST" and form.is_valid():
        session = form.save(commit=False)
        session.created_by = request.user
        session.save()
        MeetingSession.sync_statuses()
        messages.success(request, "Session created.")
        return redirect("manage_session_detail", pk=session.pk)
    return render(request, "meetings/manage/session_form.html", {"form": form, "title": "Create session"})


@admin_required
def session_edit(request, pk):
    with transaction.atomic():
        session = get_object_or_404(MeetingSession.objects.select_for_update(), pk=pk)
        if session.effective_status() not in (Status.SCHEDULED, Status.OPEN):
            messages.error(request, "Only scheduled or open sessions can be edited.")
            return redirect("manage_session_detail", pk=pk)
        form = SessionForm(request.POST or None, instance=session)
        if request.method == "POST" and form.is_valid():
            form.save()
            MeetingSession.sync_statuses()
            messages.success(request, "Session updated.")
            return redirect("manage_session_detail", pk=pk)
    return render(request, "meetings/manage/session_form.html", {"form": form, "title": "Edit session"})


def _run_session_action(request, pk, func, success):
    try:
        func(pk, request.user)
    except AttendanceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, success)
    return redirect("manage_session_detail", pk=pk)


@admin_required
@require_POST
def session_finalize(request, pk):
    return _run_session_action(request, pk, finalize_session, "Session finalized. It now counts in official statistics.")


@admin_required
@require_POST
def session_close(request, pk):
    return _run_session_action(request, pk, close_session_now, "Session closed.")


@admin_required
@require_POST
def session_delete(request, pk):
    try:
        label, records = delete_session(pk, request.user)
    except AttendanceError as exc:
        messages.error(request, str(exc))
        return redirect("manage_sessions")
    messages.success(request, f"Deleted {label} and {records} attendance record(s).")
    return redirect("manage_sessions")


@admin_required
@require_POST
def attendance_delete(request, pk, user_id):
    try:
        delete_attendance(session_id=pk, user_id=user_id, actor=request.user)
    except AttendanceError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Attendance record deleted and logged in the audit log.")
    return redirect("manage_session_detail", pk=pk)


@admin_required
def session_detail(request, pk):
    MeetingSession.sync_statuses()
    session = get_object_or_404(MeetingSession, pk=pk)
    show = "absent" if request.GET.get("show") == "absent" else "present"
    q = request.GET.get("q", "").strip()[:100]
    row = session_rows(annotate_counts(MeetingSession.objects.filter(pk=pk)))[0]
    if show == "present":
        qs = AttendanceRecord.objects.filter(session=session).select_related("user", "recorded_by")
        for term in q.split():
            qs = qs.filter(Q(user__full_name__icontains=term) | Q(user__student_id__icontains=term))
        qs = qs.order_by("user__full_name")
    else:
        present = AttendanceRecord.objects.filter(session=session, user=OuterRef("pk"))
        qs = search_users(User.objects.filter(is_active=True), q).filter(~Exists(present)).order_by("full_name")
    page_obj, query = paginate(request, qs)
    return render(request, "meetings/manage/session_detail.html", {
        "session": session, "row": row, "state": session.effective_status(), "show": show, "q": q,
        "page_obj": page_obj, "qs": query,
        "can_correct": session.effective_status() in (Status.CLOSED, Status.FINALIZED),
        "recent_audit": session.audit_entries.select_related("user", "performed_by")[:5],
    })


@admin_required
def session_csv(request, pk):
    session = get_object_or_404(MeetingSession, pk=pk)
    present = {r.user_id: r for r in AttendanceRecord.objects.filter(session=session).select_related("recorded_by")}
    users = User.objects.filter(is_active=True) | User.objects.filter(pk__in=present.keys())
    rows = []
    for u in users.distinct().order_by("full_name"):
        rec = present.get(u.pk)
        rows.append([u.full_name, u.student_id, "Present" if rec else "Absent",
                     timezone.localtime(rec.recorded_at).isoformat(timespec="seconds") if rec else "",
                     rec.recorded_by.student_id if rec else ""])
    return _csv_response(f"session_{session.pk}_attendance.csv",
                         ["Full name", "Student ID", "Status", "Recorded at", "Recorded by (ID)"], rows)


@admin_required
def correction(request, pk, user_id):
    session = get_object_or_404(MeetingSession, pk=pk)
    person = get_object_or_404(User, pk=user_id)
    record = AttendanceRecord.objects.filter(session=session, user=person).select_related("recorded_by").first()
    action = AttendanceAuditLog.Action.REMOVE if record else AttendanceAuditLog.Action.ADD
    form = CorrectionForm(request.POST or None, initial={"action": action})
    if request.method == "POST" and form.is_valid():
        try:
            correct_attendance(session_id=session.pk, user_id=person.pk, action=form.cleaned_data["action"],
                               reason=form.cleaned_data["reason"], actor=request.user)
        except AttendanceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Correction saved and recorded in the audit log.")
            return redirect("manage_session_detail", pk=pk)
    return render(request, "meetings/manage/correction.html", {
        "session": session, "person": person, "record": record, "form": form, "action": action,
        "can_correct": session.effective_status() in (Status.CLOSED, Status.FINALIZED)})


@admin_required
def users(request):
    q = request.GET.get("q", "").strip()[:100]
    role = request.GET.get("role", "")
    qs = search_users(User.objects.all(), q).prefetch_related("groups")
    if role == "usher":
        qs = qs.filter(groups__name=USHER_GROUP)
    elif role == "admin":
        qs = qs.filter(is_superuser=True)
    elif role == "subadmin":
        qs = qs.filter(groups__name=SUB_ADMIN_GROUP)
    page_obj, query = paginate(request, qs.order_by("full_name", "student_id"))
    return render(request, "meetings/manage/users.html", {"page_obj": page_obj, "qs": query, "q": q, "role": role})


@admin_required
@require_POST
def user_role(request, pk):
    func = roles.ACTIONS.get(request.POST.get("action", ""))
    get_object_or_404(User, pk=pk)
    if func is None:
        messages.error(request, "Unknown role action.")
    else:
        try:
            user = func(pk, request.user)
        except roles.RoleError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Updated roles for {user.full_name}.")
    nxt = request.POST.get("qs", "")
    return redirect(f"/manage/users/?{nxt}" if nxt else "manage_users")


@admin_required
def user_detail(request, pk):
    person = get_object_or_404(User, pk=pk)
    page_obj, query = paginate(request, history_qs(person))
    return render(request, "meetings/manage/user_detail.html", {
        "person": person, "stats": user_stats(person), "page_obj": page_obj, "qs": query,
        "extra_sessions": person.attendance_records.exclude(session__status=Status.FINALIZED).count()})


@admin_required
def audit_log(request):
    qs = AttendanceAuditLog.objects.select_related("session", "user", "performed_by")
    session_id = request.GET.get("session", "")
    if session_id.isdigit():
        qs = qs.filter(session_id=session_id)
    page_obj, query = paginate(request, qs)
    return render(request, "meetings/manage/audit.html", {"page_obj": page_obj, "qs": query})