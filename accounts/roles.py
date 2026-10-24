"""Role management. Admin == superuser; usher == member of the Usher group.
The usher group carries the `meetings.take_attendance` permission."""
from django.contrib.auth.models import Group, Permission
from django.db import transaction

from .models import SUB_ADMIN_GROUP, USHER_GROUP, User


class RoleError(Exception):
    pass


def _permissions(*codenames):
    return list(Permission.objects.filter(content_type__app_label="meetings", codename__in=codenames))


def get_usher_group():
    """Return the Usher group, creating it (with its permission) if needed."""
    group, _ = Group.objects.get_or_create(name=USHER_GROUP)
    group.permissions.add(*_permissions("take_attendance"))
    return group


def get_sub_admin_group():
    """Sub admins: every app admin page and the usher screen, but no Django Admin (they are never is_staff)."""
    group, _ = Group.objects.get_or_create(name=SUB_ADMIN_GROUP)
    group.permissions.add(*_permissions("take_attendance", "manage_app"))
    return group


def _require_manager(actor):
    if not (actor.is_authenticated and actor.is_active and actor.is_app_admin):
        raise RoleError("Only administrators can change roles.")


def _require_superuser(actor):
    if not (actor.is_authenticated and actor.is_active and actor.is_superuser):
        raise RoleError("Only the main administrator can change admin roles.")


def grant_usher(user_id, actor):
    _require_manager(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.is_active:
            raise RoleError("This account is inactive.")
        user.groups.add(get_usher_group())
    return user


def revoke_usher(user_id, actor):
    _require_manager(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.groups.remove(get_usher_group())
    return user


def grant_admin(user_id, actor):
    _require_superuser(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.is_active:
            raise RoleError("This account is inactive.")
        User.objects.filter(pk=user.pk).update(is_superuser=True, is_staff=True)
    return user


def revoke_admin(user_id, actor):
    _require_superuser(actor)
    with transaction.atomic():
        # Lock every active admin row so two concurrent demotions cannot both pass.
        admin_ids = list(User.objects.select_for_update().filter(is_superuser=True, is_active=True)
                         .values_list("pk", flat=True))
        user = User.objects.get(pk=user_id)
        if user.pk in admin_ids and len(admin_ids) <= 1:
            raise RoleError("You cannot remove the last administrator.")
        User.objects.filter(pk=user.pk).update(is_superuser=False, is_staff=False)
    return user


def grant_sub_admin(user_id, actor):
    _require_superuser(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        if not user.is_active:
            raise RoleError("This account is inactive.")
        user.groups.add(get_sub_admin_group())
    return user


def revoke_sub_admin(user_id, actor):
    _require_superuser(actor)
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        user.groups.remove(get_sub_admin_group())
    return user


ACTIONS = {
    "grant_usher": grant_usher,
    "revoke_usher": revoke_usher,
    "grant_admin": grant_admin,
    "revoke_admin": revoke_admin,
    "grant_sub_admin": grant_sub_admin,
    "revoke_sub_admin": revoke_sub_admin,
}