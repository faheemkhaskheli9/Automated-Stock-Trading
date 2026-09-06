from django.urls import path

from .views import backtest

app_name = "strategies"
urlpatterns = [path("", backtest, name="backtest")]
