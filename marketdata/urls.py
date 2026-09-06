from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "marketdata"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("instruments/", views.instruments, name="instruments"),
    path("sync/", views.sync_history, name="sync"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="marketdata/login.html", next_page="/"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="marketdata:login"), name="logout"),
]
