"""Role management. Admin == superuser; usher == member of the Usher group.
The usher group carries the `meetings.take_attendance` permission."""
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from .models import USHER_GROUP, User


class RoleError(Exception):
    pass


def get_usher_group():
    """Return the Usher group, creating it (with its permission) if needed."""
    group, _ = Group.objects.get_or_create(name=USHER_GROUP)
    perm = Permission.objects.filter(content_type__app_label="meetings", codename="take_attendance").first()
    if perm:
        group.permissions.add(perm)
    return group


def _require_admin(actor):
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser):
        raise RoleError("Only administrators can change roles.")


def grant_usher(user_id, actor):
    _require_admin(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.is_active:
            raise RoleError("This account is inactive.")
        user.groups.add(get_usher_group())
    return user


def revoke_usher(user_id, actor):
    _require_admin(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.groups.remove(get_usher_group())
    return user


def grant_admin(user_id, actor):
    _require_admin(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.is_active:
            raise RoleError("This account is inactive.")
        User.objects.filter(pk=user.pk).update(is_superuser=True, is_staff=True)
    return user


def revoke_admin(user_id, actor):
    _require_admin(actor)
    with transaction.atomic():
        # Lock every active admin row so two concurrent demotions cannot both pass.
        admin_ids = list(User.objects.select_for_update().filter(is_superuser=True, is_active=True)
                         .values_list("pk", flat=True))
        user = User.objects.get(pk=user_id)
        if user.pk in admin_ids and len(admin_ids) <= 1:
            raise RoleError("You cannot remove the last administrator.")
        User.objects.filter(pk=user.pk).update(is_superuser=False, is_staff=False)
    return user


ACTIONS = {
    "grant_usher": grant_usher,
    "revoke_usher": revoke_usher,
    "grant_admin": grant_admin,
    "revoke_admin": revoke_admin,
}
