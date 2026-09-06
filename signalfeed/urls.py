from django.urls import path

from . import views

app_name = "signalfeed"
urlpatterns = [
    path("", views.index, name="index"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("watchlist/", views.watchlist, name="watchlist"),
    path("watchlist/new/", views.watch_edit, name="watch_create"),
    path("watchlist/<int:pk>/edit/", views.watch_edit, name="watch_edit"),
    path("watchlist/<int:pk>/delete/", views.watch_delete, name="watch_delete"),
    path("run/", views.run, name="run"),
]
