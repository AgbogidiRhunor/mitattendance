from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class ImmutableRecordError(Exception):
    pass


class MeetingSession(models.Model):
    """Lifecycle: SCHEDULED -> OPEN -> CLOSED -> FINALIZED.

    SCHEDULED/OPEN/CLOSED are driven by the clock (see effective_status) and
    persisted lazily; CLOSED -> FINALIZED is an explicit admin action. The
    clock, not the stored value, decides whether attendance is accepted."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        FINALIZED = "finalized", "Finalized"

    title = models.CharField(max_length=200)
    meeting_date = models.DateField()
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-meeting_date", "-opens_at"]
        indexes = [
            models.Index(fields=["status", "closes_at"]),
            models.Index(fields=["meeting_date"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(closes_at__gt=F("opens_at")), name="session_closes_after_opens"),
        ]
        permissions = [("take_attendance", "Can record attendance for open sessions")]

    def __str__(self):
        return f"{self.title} ({self.meeting_date})"

    def clean(self):
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValidationError({"closes_at": "The closing time must be after the opening time."})

    def effective_status(self, now=None):
        now = now or timezone.now()
        if self.status in (self.Status.FINALIZED, self.Status.CLOSED):
            return self.status
        if now >= self.closes_at:
            return self.Status.CLOSED
        if now >= self.opens_at:
            return self.Status.OPEN
        return self.Status.SCHEDULED

    def is_accepting_attendance(self, now=None):
        return self.effective_status(now) == self.Status.OPEN

    @classmethod
    def sync_statuses(cls, now=None):
        """Persist clock-driven transitions. Optional for correctness."""
        now = now or timezone.now()
        pending = cls.objects.filter(status__in=[cls.Status.SCHEDULED, cls.Status.OPEN])
        closed = pending.filter(closes_at__lte=now).update(status=cls.Status.CLOSED, closed_at=F("closes_at"))
        opened = cls.objects.filter(status=cls.Status.SCHEDULED, opens_at__lte=now, closes_at__gt=now) \
            .update(status=cls.Status.OPEN)
        return closed, opened

    @classmethod
    def open_now(cls, now=None):
        now = now or timezone.now()
        return cls.objects.filter(status__in=[cls.Status.SCHEDULED, cls.Status.OPEN],
                                  opens_at__lte=now, closes_at__gt=now)


class AttendanceRecord(models.Model):
    """Existence of a row == the user was present. Rows are insert-only:
    ushers have no code path that updates or deletes them, and only the audited
    correction service (queryset delete) can remove one."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="attendance_records")
    session = models.ForeignKey(MeetingSession, on_delete=models.PROTECT, related_name="attendance_records")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="unique_attendance_per_session_user"),
        ]

    def __str__(self):
        return f"{self.user_id} @ session {self.session_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Saved attendance records cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Attendance records can only be removed through an audited correction.")


class AttendanceAuditLog(models.Model):
    class Action(models.TextChoices):
        ADD = "add", "Marked present"
        REMOVE = "remove", "Marked absent"

    # Plain integer (not FK) so the entry stays meaningful after a record is removed.
    attendance_record_id = models.PositiveBigIntegerField(null=True, blank=True)
    session = models.ForeignKey(MeetingSession, on_delete=models.PROTECT, related_name="audit_entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_entries")
    action = models.CharField(max_length=10, choices=Action.choices)
    original_values = models.JSONField()
    corrected_values = models.JSONField()
    reason = models.TextField()
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["session", "created_at"]), models.Index(fields=["user"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Audit entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Audit entries cannot be deleted.")
