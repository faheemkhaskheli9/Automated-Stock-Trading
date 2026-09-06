from django.urls import path

from . import views

app_name = "signalfeed"
urlpatterns = [
    path("", views.index, name="index"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
]
