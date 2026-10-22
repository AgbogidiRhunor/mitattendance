from django.contrib import admin

from .models import AttendanceAuditLog, AttendanceRecord, MeetingSession


class ReadOnlyAdmin(admin.ModelAdmin):
    """Inspection only: changes go through the application so rules and audit trail apply."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MeetingSession)
class MeetingSessionAdmin(ReadOnlyAdmin):
    list_display = ("title", "meeting_date", "status", "opens_at", "closes_at", "finalized_at")
    list_filter = ("status",)
    search_fields = ("title",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ReadOnlyAdmin):
    list_display = ("user", "session", "recorded_by", "recorded_at")
    list_select_related = ("user", "session", "recorded_by")
    search_fields = ("user__full_name", "user__student_id")


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "session", "user", "action", "performed_by")
    list_select_related = ("session", "user", "performed_by")
    search_fields = ("user__full_name", "user__student_id", "reason")
