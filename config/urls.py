from django.contrib import admin
from django.urls import include, path

handler403 = "meetings.views.error_403"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("meetings.urls")),
]
