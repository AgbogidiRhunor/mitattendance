"""Shared (any signed-in user) and usher views."""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User, normalize_student_id

from .decorators import usher_required
from .models import AttendanceRecord, MeetingSession
from .services import AttendanceError, record_attendance
from .stats import history_qs, user_stats
from .utils import paginate, search_users


def error_403(request, exception=None):
    return render(request, "403.html", status=403)


@login_required
def dashboard(request):
    return render(request, "meetings/dashboard.html", {
        "stats": user_stats(request.user),
        "recent": history_qs(request.user)[:5],
    })


@login_required
def history(request):
    page_obj, qs = paginate(request, history_qs(request.user))
    return render(request, "meetings/history.html", {"page_obj": page_obj, "qs": qs})


@usher_required
def usher_sessions(request):
    MeetingSession.sync_statuses()
    return render(request, "meetings/usher_sessions.html", {"sessions": MeetingSession.open_now().order_by("closes_at")})


@usher_required
def usher_attendance(request, pk):
    MeetingSession.sync_statuses()
    session = get_object_or_404(MeetingSession, pk=pk)

    if request.method == "POST":
        back = {}
        if request.POST.get("q", "").strip():
            back["q"] = request.POST["q"].strip()[:100]
        if request.POST.get("page", "").isdigit():
            back["page"] = request.POST["page"]
        target = reverse("usher_attendance", args=[session.pk])
        if request.POST.get("session_id") != str(session.pk):
            messages.error(request, "The submission did not match this session. Nothing was saved.")
            return redirect(f"{target}?{urlencode(back)}" if back else target)
        try:
            result = record_attendance(session_id=session.pk, raw_user_ids=request.POST.getlist("user_ids"),
                                       actor=request.user)
        except AttendanceError as exc:
            messages.error(request, f"{exc} Nothing was saved.")
            session.refresh_from_db()
            if not session.is_accepting_attendance():
                return redirect("usher_sessions")
        else:
            msg = f"Saved attendance for {result['created']} person(s)."
            if result["already_recorded"]:
                msg += f" {result['already_recorded']} were already recorded and were left unchanged."
            messages.success(request, msg)
        return redirect(f"{target}?{urlencode(back)}" if back else target)

    if not session.is_accepting_attendance():
        messages.warning(request, "This session is not open for attendance.")
        return redirect("usher_sessions")

    q = request.GET.get("q", "").strip()[:100]
    signed = AttendanceRecord.objects.filter(session=session, user=OuterRef("pk"))
    people = search_users(User.objects.filter(is_active=True), q).annotate(signed=Exists(signed)) \
        .order_by("full_name", "student_id")
    page_obj, qs = paginate(request, people, settings.ATTENDANCE_PAGE_SIZE)
    return render(request, "meetings/usher_attendance.html", {
        "session": session, "page_obj": page_obj, "qs": qs, "q": q,
        "total_matching": page_obj.paginator.count,
        "signed_total": AttendanceRecord.objects.filter(session=session).count(),
    })
