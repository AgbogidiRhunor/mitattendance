from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_usher_group(sender, **kwargs):
    from accounts.roles import get_sub_admin_group, get_usher_group

    get_usher_group()
    get_sub_admin_group()


class MeetingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "meetings"

    def ready(self):
        post_migrate.connect(ensure_usher_group, sender=self)