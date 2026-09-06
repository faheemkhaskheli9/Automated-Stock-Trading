from django.urls import path

from . import views

app_name = "portfolio"
urlpatterns = [
    path("", views.account_list, name="account_list"),
    path("new/", views.account_edit, name="account_create"),
    path("<int:pk>/", views.account_detail, name="account_detail"),
    path("<int:pk>/edit/", views.account_edit, name="account_edit"),
]
