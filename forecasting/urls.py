from django.urls import path

from . import views

app_name = "forecasting"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.new, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
]
