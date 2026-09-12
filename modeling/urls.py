from django.urls import path

from . import views

app_name = "modeling"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.edit, name="create"),
    path("estimators/", views.estimators, name="estimators"),
    path("leaderboard/", views.leaderboard, name="leaderboard"),
    path("weekday-suite/", views.weekday_suite, name="weekday_suite"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/predict/", views.predict_view, name="predict"),
]
