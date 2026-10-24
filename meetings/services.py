"""All state-changing attendance logic. Views stay thin; every rule is enforced
here, inside transactions that lock the session row."""
import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from accounts.models import ATTENDANCE_PERMISSION, MANAGE_PERMISSION, User

from .models import AttendanceAuditLog, AttendanceRecord, MeetingSession

logger = logging.getLogger(__name__)

MAX_BATCH = 500
Status = MeetingSession.Status


class AttendanceError(Exception):
    """A rule was violated; str(exc) is safe to show to the user."""


def _lock_session(session_id):
    try:
        return MeetingSession.objects.select_for_update().get(pk=session_id)
    except (MeetingSession.DoesNotExist, ValueError, TypeError):
        raise AttendanceError("Session not found.")


def parse_user_ids(raw_values):
    ids = []
    for raw in raw_values:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            raise AttendanceError("The submission contained an invalid user ID.")
        if value <= 0:
            raise AttendanceError("The submission contained an invalid user ID.")
        ids.append(value)
    if not ids:
        raise AttendanceError("Select at least one person before saving.")
    if len(ids) != len(set(ids)):
        raise AttendanceError("The submission contained duplicate user IDs.")
    if len(ids) > MAX_BATCH:
        raise AttendanceError(f"You can save at most {MAX_BATCH} people at once.")
    return ids


def record_attendance(*, session_id, raw_user_ids, actor, now=None):
    """Bulk-record attendance. All-or-nothing; never overwrites existing records."""
    if not (actor.is_authenticated and actor.is_active and actor.has_perm(ATTENDANCE_PERMISSION)):
        raise PermissionDenied
    ids = parse_user_ids(raw_user_ids)
    with transaction.atomic():
        session = _lock_session(session_id)  # serialises concurrent submissions and admin close
        now = now or timezone.now()
        if not session.is_accepting_attendance(now):
            raise AttendanceError("This session is not open for attendance.")
        eligible = set(User.objects.filter(pk__in=ids, is_active=True).values_list("pk", flat=True))
        if len(eligible) != len(ids):
            raise AttendanceError("One or more selected people are not eligible for attendance.")
        existing = set(AttendanceRecord.objects.filter(session=session, user_id__in=ids)
                       .values_list("user_id", flat=True))
        new_ids = [i for i in ids if i not in existing]
        AttendanceRecord.objects.bulk_create(
            [AttendanceRecord(session=session, user_id=i, recorded_by=actor, recorded_at=now) for i in new_ids],
            ignore_conflicts=True,
        )
    return {"created": len(new_ids), "already_recorded": len(existing)}


def _snapshot(record):
    if record is None:
        return {"present": False}
    return {
        "present": True,
        "user_id": record.user_id,
        "session_id": record.session_id,
        "recorded_by_id": record.recorded_by_id,
        "recorded_at": record.recorded_at.isoformat(),
    }


def correct_attendance(*, session_id, user_id, action, reason, actor, now=None):
    """Admin-only, audited correction. Allowed once a session is closed or finalized."""
    if not (actor.is_authenticated and actor.is_active and actor.has_perm(MANAGE_PERMISSION)):
        raise PermissionDenied
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise AttendanceError("Give a reason for the correction (at least 5 characters).")
    if action not in (AttendanceAuditLog.Action.ADD, AttendanceAuditLog.Action.REMOVE):
        raise AttendanceError("Unknown correction action.")
    with transaction.atomic():
        session = _lock_session(session_id)
        if session.effective_status(now) not in (Status.CLOSED, Status.FINALIZED):
            raise AttendanceError("Corrections are only allowed after a session has closed.")
        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            raise AttendanceError("User not found.")
        record = AttendanceRecord.objects.filter(session=session, user=user).first()
        if action == AttendanceAuditLog.Action.ADD:
            if record:
                raise AttendanceError("This person is already marked present.")
            if not user.is_active:
                raise AttendanceError("Inactive accounts cannot be marked present.")
            original = _snapshot(None)
            record = AttendanceRecord.objects.create(session=session, user=user, recorded_by=actor)
            corrected = _snapshot(record)
            record_id = record.pk
        else:
            if not record:
                raise AttendanceError("This person is not marked present.")
            original, corrected, record_id = _snapshot(record), _snapshot(None), record.pk
            AttendanceRecord.objects.filter(pk=record.pk).delete()  # queryset delete: audited path only
        return AttendanceAuditLog.objects.create(
            attendance_record_id=record_id, session=session, user=user, action=action,
            original_values=original, corrected_values=corrected, reason=reason, performed_by=actor,
        )


def finalize_session(session_id, actor, now=None):
    if not (actor.is_authenticated and actor.is_active and actor.has_perm(MANAGE_PERMISSION)):
        raise PermissionDenied
    with transaction.atomic():
        session = _lock_session(session_id)
        now = now or timezone.now()
        state = session.effective_status(now)
        if state == Status.FINALIZED:
            raise AttendanceError("This session is already finalized.")
        if state != Status.CLOSED:
            raise AttendanceError("A session can only be finalized after it has closed.")
        session.status = Status.FINALIZED
        session.closed_at = session.closed_at or min(session.closes_at, now)
        session.finalized_at = now
        session.save(update_fields=["status", "closed_at", "finalized_at"])
    return session


def close_session_now(session_id, actor, now=None):
    if not (actor.is_authenticated and actor.is_active and actor.has_perm(MANAGE_PERMISSION)):
        raise PermissionDenied
    with transaction.atomic():
        session = _lock_session(session_id)
        now = now or timezone.now()
        if session.effective_status(now) not in (Status.SCHEDULED, Status.OPEN):
            raise AttendanceError("This session is already closed.")
        session.status = Status.CLOSED
        session.closed_at = now
        session.save(update_fields=["status", "closed_at"])
    return session


def delete_attendance(*, session_id, user_id, actor):
    """Main admin only. Hard-deletes one attendance record in any session state, with an audit entry."""
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser):
        raise PermissionDenied
    with transaction.atomic():
        session = _lock_session(session_id)
        record = AttendanceRecord.objects.filter(session=session, user_id=user_id).select_related("user").first()
        if not record:
            raise AttendanceError("This person is not marked present.")
        entry = AttendanceAuditLog.objects.create(
            attendance_record_id=record.pk, session=session, user=record.user,
            action=AttendanceAuditLog.Action.REMOVE, original_values=_snapshot(record),
            corrected_values=_snapshot(None), reason="Deleted from the admin dashboard", performed_by=actor,
        )
        AttendanceRecord.objects.filter(pk=record.pk).delete()  # queryset delete: audited path only
    return entry


def delete_session(session_id, actor):
    """Main admin only. Deletes a session with its attendance records and audit entries (PROTECT blocks a plain delete)."""
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser):
        raise PermissionDenied
    with transaction.atomic():
        session = _lock_session(session_id)
        label = str(session)
        audit_deleted = AttendanceAuditLog.objects.filter(session=session).delete()[0]
        records_deleted = AttendanceRecord.objects.filter(session=session).delete()[0]
        MeetingSession.objects.filter(pk=session.pk).delete()
    logger.warning("Session %r (id=%s) deleted by %s (id=%s): %s attendance record(s), %s audit entr(ies) removed",
                   label, session_id, actor.student_id, actor.pk, records_deleted, audit_deleted)
    return label, records_deleted