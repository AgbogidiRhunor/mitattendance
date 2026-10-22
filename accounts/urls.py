from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
