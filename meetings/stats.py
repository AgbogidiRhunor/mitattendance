"""Statistics are always computed from the database, from FINALIZED sessions.

Definitions
- Eligible users for a session = currently active accounts, plus any inactive
  account that has a record for that session (so absences are never negative).
- Absences = eligible - attendees; percentage = attendees / eligible * 100.
- Personal missed = meetings held - attended (every finalized session applies
  to every account; there are no per-user eligibility rules yet).
"""
from django.db.models import Count, Exists, OuterRef, Q

from accounts.models import User

from .models import AttendanceRecord, MeetingSession

FINALIZED = MeetingSession.Status.FINALIZED


def pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def user_stats(user):
    held = MeetingSession.objects.count()  # every session created, whatever its status
    attended = AttendanceRecord.objects.filter(user=user).count()
    return {"held": held, "attended": attended, "missed": held - attended, "percent": pct(attended, held)}


def history_qs(user):
    """All sessions with a `present` flag for this user."""
    mine = AttendanceRecord.objects.filter(session=OuterRef("pk"), user=user)
    return MeetingSession.objects.annotate(present=Exists(mine)) \
        .order_by("-meeting_date", "-opens_at")


def annotate_counts(qs):
    return qs.annotate(
        attendee_count=Count("attendance_records"),
        inactive_attendees=Count("attendance_records", filter=Q(attendance_records__user__is_active=False)),
    )


def session_rows(sessions):
    """Turn annotated sessions (already sliced/paginated) into report rows."""
    active_total = User.objects.filter(is_active=True).count()
    rows = []
    for s in sessions:
        eligible = active_total + s.inactive_attendees
        rows.append({
            "session": s, "eligible": eligible, "attendees": s.attendee_count,
            "absent": eligible - s.attendee_count, "percent": pct(s.attendee_count, eligible),
        })
    return rows


def period_totals(finalized_sessions):
    """Aggregate totals for a queryset of finalized sessions."""
    n = finalized_sessions.count()
    active_total = User.objects.filter(is_active=True).count()
    records = AttendanceRecord.objects.filter(session__in=finalized_sessions)
    attendance = records.count()
    inactive_attendance = records.filter(user__is_active=False).count()
    slots = active_total * n + inactive_attendance
    return {"sessions": n, "attendance": attendance, "absences": slots - attendance, "percent": pct(attendance, slots)}
