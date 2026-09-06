from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from backtesting.models import Backtest, BacktestRun
from execution.models import Order, Trade
from marketdata.models import Instrument, PriceBar
from modeling.models import ModelPrediction, TradingModel
from portfolio.models import Account, Position
from research.models import NewsItem, ResearchSnapshot
from risk.models import RiskDecision
from strategies.models import Strategy

from .serializers import (
    AccountSerializer,
    BacktestRunSerializer,
    BacktestSerializer,
    InstrumentSerializer,
    ModelPredictionSerializer,
    NewsItemSerializer,
    OrderSerializer,
    PositionSerializer,
    PriceBarSerializer,
    ResearchSnapshotSerializer,
    RiskDecisionSerializer,
    StrategySerializer,
    TradeSerializer,
    TradingModelSerializer,
)


class SymbolFilterMixin:
    """Adds ?symbol=ENGRO scoping via `symbol_lookup` (an ORM path). Kept
    hand-rolled for the same reason as PriceBarViewSet - no django-filter."""

    symbol_lookup: str = "symbol"

    def get_queryset(self):
        qs = super().get_queryset()
        symbol = self.request.query_params.get("symbol")
        if symbol:
            qs = qs.filter(**{self.symbol_lookup: symbol.upper()})
        return qs


class OwnerScopedMixin:
    """Restricts a queryset to rows the requesting user owns, via
    `owner_lookup` (an ORM path ending at an Account's `owner`). Staff see
    everything - useful for an operator managing multiple accounts."""

    owner_lookup: str = "owner"

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_staff:
            return qs
        return qs.filter(Q(**{self.owner_lookup: self.request.user}))


class InstrumentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Reference data - not account-scoped, visible to any authenticated user."""

    queryset = Instrument.objects.all()
    serializer_class = InstrumentSerializer
    permission_classes = [IsAuthenticated]


class PriceBarViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Supports ?symbol=ENGRO to scope to one instrument - there's no
    django-filter dependency in this project, so this is done by hand
    rather than via `filterset_fields` (which needs that package)."""

    queryset = PriceBar.objects.select_related("instrument").all()
    serializer_class = PriceBarSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        symbol = self.request.query_params.get("symbol")
        if symbol:
            qs = qs.filter(instrument__symbol=symbol.upper())
        return qs


class StrategyViewSet(OwnerScopedMixin, viewsets.ModelViewSet):
    """Read + the on/off toggle (`is_active`) from docs/PLAN.md, Phase 4 -
    everything else is read-only, see StrategySerializer."""

    queryset = Strategy.objects.select_related("account").all()
    serializer_class = StrategySerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "account__owner"
    http_method_names = ["get", "patch", "head", "options"]


class AccountViewSet(
    OwnerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "owner"


class PositionViewSet(
    OwnerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Position.objects.select_related("account", "instrument").all()
    serializer_class = PositionSerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "account__owner"


class OrderViewSet(
    OwnerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = (
        Order.objects.select_related("account", "instrument", "strategy")
        .prefetch_related("trades")
        .all()
    )
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "account__owner"


class TradeViewSet(
    OwnerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = Trade.objects.select_related("order__account").all()
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "order__account__owner"


class RiskDecisionViewSet(
    OwnerScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    queryset = RiskDecision.objects.select_related("account", "instrument").all()
    serializer_class = RiskDecisionSerializer
    permission_classes = [IsAuthenticated]
    owner_lookup = "account__owner"


# --- Phase 7: research / forecasting read API -------------------------------
#
# Operator-global config + reference data - no OwnerScopedMixin. Read-only
# except TradingModel's is_active toggle (see StrategyViewSet).


class _ReadOnlyViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]


class NewsItemViewSet(SymbolFilterMixin, _ReadOnlyViewSet):
    """Ingested headlines + VADER sentiment. Supports ?symbol=ENGRO."""

    queryset = NewsItem.objects.all()
    serializer_class = NewsItemSerializer


class ResearchSnapshotViewSet(SymbolFilterMixin, _ReadOnlyViewSet):
    """Frozen point-in-time feature bundles. Supports ?symbol=ENGRO."""

    queryset = ResearchSnapshot.objects.all()
    serializer_class = ResearchSnapshotSerializer


class ModelPredictionViewSet(SymbolFilterMixin, _ReadOnlyViewSet):
    """Stored forecasts with backfilled actuals. Supports ?symbol=ENGRO."""

    queryset = ModelPrediction.objects.select_related("model", "instrument").all()
    serializer_class = ModelPredictionSerializer
    symbol_lookup = "instrument__symbol"


class BacktestViewSet(_ReadOnlyViewSet):
    queryset = Backtest.objects.select_related("model").prefetch_related("runs").all()
    serializer_class = BacktestSerializer


class BacktestRunViewSet(_ReadOnlyViewSet):
    queryset = BacktestRun.objects.select_related("backtest").all()
    serializer_class = BacktestRunSerializer


class TradingModelViewSet(_ReadOnlyViewSet, mixins.UpdateModelMixin):
    """Read + the is_active on/off toggle, mirroring StrategyViewSet."""

    queryset = TradingModel.objects.prefetch_related("instruments").all()
    serializer_class = TradingModelSerializer
    http_method_names = ["get", "patch", "head", "options"]
