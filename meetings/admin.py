from django.contrib import admin
from django.db import transaction

from .models import AttendanceAuditLog, AttendanceRecord, MeetingSession
from .services import _snapshot, delete_session


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

    def has_delete_permission(self, request, obj=None):
        # Only the main administrator (superuser) may delete; sub admins cannot even log in here.
        return request.user.is_active and request.user.is_superuser

    def get_deleted_objects(self, objs, request):
        # The database links to attendance records and audit entries are PROTECTed, so Django's default
        # confirmation page would refuse. delete_session() removes them first, so describe that instead.
        ids = [o.pk for o in objs]
        records = AttendanceRecord.objects.filter(session_id__in=ids).count()
        audits = AttendanceAuditLog.objects.filter(session_id__in=ids).count()
        listing = [f"Meeting session: {o}" for o in objs]
        listing.append(f"{records} attendance record(s) and {audits} audit entr(ies) will also be deleted.")
        return listing, {"meeting sessions": len(ids)}, set(), []

    def delete_model(self, request, obj):
        delete_session(obj.pk, request.user)

    def delete_queryset(self, request, queryset):
        for pk in list(queryset.values_list("pk", flat=True)):
            delete_session(pk, request.user)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(ReadOnlyAdmin):
    list_display = ("user", "session", "recorded_by", "recorded_at")
    list_select_related = ("user", "session", "recorded_by")
    search_fields = ("user__full_name", "user__student_id")
    list_filter = ("session",)

    def has_delete_permission(self, request, obj=None):
        # Only the main administrator (superuser) may delete; sub admins cannot even log in here.
        return request.user.is_active and request.user.is_superuser

    def _delete_with_audit(self, request, queryset):
        with transaction.atomic():
            records = list(queryset.select_related("user", "session", "recorded_by"))
            for r in records:
                AttendanceAuditLog.objects.create(
                    attendance_record_id=r.pk, session=r.session, user=r.user,
                    action=AttendanceAuditLog.Action.REMOVE, original_values=_snapshot(r),
                    corrected_values={"present": False}, reason="Deleted in Django Admin",
                    performed_by=request.user)
            AttendanceRecord.objects.filter(pk__in=[r.pk for r in records]).delete()  # queryset delete

    def delete_model(self, request, obj):
        self._delete_with_audit(request, AttendanceRecord.objects.filter(pk=obj.pk))

    def delete_queryset(self, request, queryset):
        self._delete_with_audit(request, queryset)


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "session", "user", "action", "performed_by")
    list_select_related = ("session", "user", "performed_by")
    search_fields = ("user__full_name", "user__student_id", "reason")