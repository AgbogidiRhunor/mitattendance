from django.urls import path

from . import admin_views as a
from . import views as v

urlpatterns = [
    path("", v.dashboard, name="dashboard"),
    path("history/", v.history, name="history"),
    path("attendance/", v.usher_sessions, name="usher_sessions"),
    path("attendance/<int:pk>/", v.usher_attendance, name="usher_attendance"),
    # Application admin
    path("manage/", a.dashboard, name="manage_dashboard"),
    path("manage/report.csv", a.report_csv, name="manage_report_csv"),
    path("manage/sessions/", a.sessions, name="manage_sessions"),
    path("manage/sessions/new/", a.session_create, name="manage_session_create"),
    path("manage/sessions/<int:pk>/", a.session_detail, name="manage_session_detail"),
    path("manage/sessions/<int:pk>/edit/", a.session_edit, name="manage_session_edit"),
    path("manage/sessions/<int:pk>/finalize/", a.session_finalize, name="manage_session_finalize"),
    path("manage/sessions/<int:pk>/close/", a.session_close, name="manage_session_close"),
    path("manage/sessions/<int:pk>/export.csv", a.session_csv, name="manage_session_csv"),
    path("manage/sessions/<int:pk>/correct/<int:user_id>/", a.correction, name="manage_correct"),
    path("manage/users/", a.users, name="manage_users"),
    path("manage/users/<int:pk>/", a.user_detail, name="manage_user_detail"),
    path("manage/users/<int:pk>/role/", a.user_role, name="manage_user_role"),
    path("manage/audit/", a.audit_log, name="manage_audit"),
]
