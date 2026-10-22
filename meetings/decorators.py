from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from accounts.models import ATTENDANCE_PERMISSION


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_app_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


def usher_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm(ATTENDANCE_PERMISSION):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper
