from django.urls import path

from . import views

app_name = "modelsearch"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.edit, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
]
