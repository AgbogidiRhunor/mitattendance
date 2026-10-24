from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm as BaseUserChangeForm

from .models import SUB_ADMIN_GROUP, USHER_GROUP, User
from .roles import get_sub_admin_group, get_usher_group


class UserCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("student_id", "full_name")


class UserChangeForm(BaseUserChangeForm):
    is_sub_admin = forms.BooleanField(
        required=False, label="Sub admin",
        help_text="Full access to the app's admin pages and the usher screen, but no Django Admin login.")
    is_usher = forms.BooleanField(required=False, label="Usher", help_text="Can record attendance on open sessions.")

    class Meta(BaseUserChangeForm.Meta):
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "is_superuser" in self.fields:
            self.fields["is_superuser"].label = "Admin"
            self.fields["is_superuser"].help_text = (
                "Main administrator: everything, including Django Admin (staff access is set automatically).")
        if self.instance and self.instance.pk:
            self.initial["is_sub_admin"] = self.instance.has_sub_admin_role
            self.initial["is_usher"] = self.instance.has_usher_role


class RoleFilter(admin.SimpleListFilter):
    title = "role"
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return [("admin", "Admin"), ("subadmin", "Sub admin"), ("usher", "Usher"), ("user", "Regular user")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "admin":
            return queryset.filter(is_superuser=True)
        if value == "subadmin":
            return queryset.filter(groups__name=SUB_ADMIN_GROUP)
        if value == "usher":
            return queryset.filter(groups__name=USHER_GROUP)
        if value == "user":
            return queryset.filter(is_superuser=False).exclude(groups__name__in=[SUB_ADMIN_GROUP, USHER_GROUP])
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    list_display = ("student_id", "full_name", "is_admin", "is_sub_admin", "is_usher", "is_regular_user",
                    "is_active", "date_joined")
    list_filter = (RoleFilter, "is_active")
    search_fields = ("student_id", "full_name")
    ordering = ("full_name",)
    fieldsets = (
        (None, {"fields": ("student_id", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        ("Roles", {"fields": ("is_superuser", "is_sub_admin", "is_usher")}),
        ("Account", {"fields": ("is_active",)}),
        ("Advanced permissions", {"fields": ("user_permissions",), "classes": ("collapse",)}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("student_id", "full_name", "password1", "password2")}),)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    @admin.display(boolean=True, description="Admin")
    def is_admin(self, obj):
        return obj.is_superuser

    @admin.display(boolean=True, description="Sub admin")
    def is_sub_admin(self, obj):
        return obj.has_sub_admin_role

    @admin.display(boolean=True, description="Usher")
    def is_usher(self, obj):
        return obj.has_usher_role

    @admin.display(boolean=True, description="User")
    def is_regular_user(self, obj):
        return not (obj.is_superuser or obj.has_sub_admin_role or obj.has_usher_role)

    def save_model(self, request, obj, form, change):
        # Only admins may log in to Django Admin; sub admins and ushers are never staff.
        obj.is_staff = obj.is_superuser
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if "is_sub_admin" in form.cleaned_data:
            user = form.instance
            for flag, get_group in (("is_sub_admin", get_sub_admin_group), ("is_usher", get_usher_group)):
                group = get_group()
                if form.cleaned_data.get(flag):
                    user.groups.add(group)
                else:
                    user.groups.remove(group)