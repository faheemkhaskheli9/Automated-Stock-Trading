from django.urls import path

from . import views

app_name = "execution"
urlpatterns = [
    path("", views.order_list, name="order_list"),
    path("place/", views.place_order, name="place_order"),
    path("run-cycle/", views.run_cycle, name="run_cycle"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
]
