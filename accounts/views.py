from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import IntegrityError
from django.shortcuts import redirect, render

from .forms import LoginForm, RegistrationForm


class AppLoginView(LoginView):
    authentication_form = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = form.save()
        except IntegrityError:  # lost a race with another registration of the same ID
            form.add_error("student_id", "An account with this student ID already exists.")
        else:
            login(request, user)
            messages.success(request, "Your account has been created.")
            return redirect("dashboard")
    return render(request, "accounts/register.html", {"form": form})
