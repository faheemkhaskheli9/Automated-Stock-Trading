from django.urls import path

from . import views

app_name = "strategies"
urlpatterns = [
    path("", views.backtest, name="backtest"),
    path("strategies/", views.strategy_list, name="strategy_list"),
    path("strategies/new/", views.strategy_edit, name="strategy_create"),
    path("strategies/<int:pk>/edit/", views.strategy_edit, name="strategy_edit"),
    path("strategies/<int:pk>/toggle/", views.strategy_toggle, name="strategy_toggle"),
    path("manual-signals/", views.manual_list, name="manual_list"),
    path("manual-signals/new/", views.manual_edit, name="manual_create"),
    path("manual-signals/<int:pk>/edit/", views.manual_edit, name="manual_edit"),
]
