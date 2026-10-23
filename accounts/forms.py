from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import User, normalize_full_name, normalize_student_id, student_id_validator


class RegistrationForm(forms.Form):
    full_name = forms.CharField(max_length=150, label="Full name")
    student_id = forms.CharField(max_length=40, label="Matriculation Number")
    password1 = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", strip=False, widget=forms.PasswordInput)

    def clean_full_name(self):
        name = normalize_full_name(self.cleaned_data["full_name"])
        if len(name) < 2:
            raise ValidationError("Enter your full name.")
        return name

    def clean_student_id(self):
        sid = normalize_student_id(self.cleaned_data["student_id"])
        student_id_validator(sid)
        if User.objects.filter(student_id=sid).exists():
            raise ValidationError("An account with this student ID already exists.")
        return sid

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                candidate = User(student_id=cleaned.get("student_id", ""), full_name=cleaned.get("full_name", ""))
                try:
                    password_validation.validate_password(p1, candidate)
                except ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self):
        # No role fields exist here: public registration can never grant elevated access.
        return User.objects.create_user(
            self.cleaned_data["student_id"], self.cleaned_data["full_name"], self.cleaned_data["password1"]
        )


class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Matriculation Number", widget=forms.TextInput(attrs={"autofocus": True}))

    error_messages = {
        "invalid_login": "Incorrect matriculation number or password.",
        "inactive": "This account is inactive.",
    }

    def clean_username(self):
        return normalize_student_id(self.cleaned_data["username"])
