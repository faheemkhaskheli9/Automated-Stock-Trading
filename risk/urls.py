from django.urls import path

from . import views

app_name = "risk"
urlpatterns = [
    path("", views.decisions, name="decisions"),
    path("equity/", views.equity_snapshots, name="equity_snapshots"),
]
