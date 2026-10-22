import re

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

USHER_GROUP = "Usher"
ATTENDANCE_PERMISSION = "meetings.take_attendance"


def normalize_student_id(value):
    """Strip all whitespace and upper-case, so 'biu / csc/1' == 'BIU/CSC/1'."""
    return re.sub(r"\s+", "", value or "").upper()


def normalize_full_name(value):
    return re.sub(r"\s+", " ", value or "").strip()


student_id_validator = RegexValidator(
    r"^[A-Z0-9][A-Z0-9/\-_.]{2,29}$",
    "Student ID must be 3-30 characters: letters, digits, and / - _ . only.",
    flags=re.IGNORECASE,
)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, student_id, full_name, password, **extra):
        if not student_id:
            raise ValueError("A student ID is required.")
        user = self.model(student_id=normalize_student_id(student_id),
                          full_name=normalize_full_name(full_name), **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, student_id, full_name, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(student_id, full_name, password, **extra)

    def create_superuser(self, student_id, full_name, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(student_id, full_name, password, **extra)

    def get_by_natural_key(self, student_id):
        return self.get(**{self.model.USERNAME_FIELD: normalize_student_id(student_id)})


class User(AbstractBaseUser, PermissionsMixin):
    """Account identified by student ID. Roles live in Django groups/permissions:
    admin == is_superuser, usher == membership of the 'Usher' group."""

    student_id = models.CharField(max_length=30, unique=True, validators=[student_id_validator])
    full_name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can sign in to Django Admin.")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "student_id"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        indexes = [models.Index(fields=["full_name"])]
        ordering = ["full_name", "student_id"]

    def __str__(self):
        return f"{self.full_name} ({self.student_id})"

    def save(self, *args, **kwargs):
        self.student_id = normalize_student_id(self.student_id)
        self.full_name = normalize_full_name(self.full_name)
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.student_id

    @property
    def is_app_admin(self):
        return self.is_active and self.is_superuser

    @property
    def has_usher_role(self):
        # Uses the prefetch cache when the caller did prefetch_related("groups").
        return any(g.name == USHER_GROUP for g in self.groups.all())
