from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("instruments", views.InstrumentViewSet, basename="instrument")
router.register("price-bars", views.PriceBarViewSet, basename="pricebar")
router.register("strategies", views.StrategyViewSet, basename="strategy")
router.register("accounts", views.AccountViewSet, basename="account")
router.register("positions", views.PositionViewSet, basename="position")
router.register("orders", views.OrderViewSet, basename="order")
router.register("trades", views.TradeViewSet, basename="trade")
router.register("risk-decisions", views.RiskDecisionViewSet, basename="riskdecision")

# Phase 7 - research / forecasting read API
router.register("news", views.NewsItemViewSet, basename="newsitem")
router.register("research-snapshots", views.ResearchSnapshotViewSet, basename="researchsnapshot")
router.register("predictions", views.ModelPredictionViewSet, basename="modelprediction")
router.register("trading-models", views.TradingModelViewSet, basename="tradingmodel")
router.register("backtests", views.BacktestViewSet, basename="backtest")
router.register("backtest-runs", views.BacktestRunViewSet, basename="backtestrun")

urlpatterns = router.urls
