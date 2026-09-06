from django.urls import path

from . import views

app_name = "research"
urlpatterns = [
    path("", views.index, name="index"),
    path("symbol/", views.symbol_detail, name="symbol_detail"),
    path("sync/", views.sync, name="sync"),
    path("fundamentals/new/", views.fundamental_edit, name="fundamental_create"),
    path("fundamentals/<int:pk>/edit/", views.fundamental_edit, name="fundamental_edit"),
]
