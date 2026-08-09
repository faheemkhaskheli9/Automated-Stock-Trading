from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from execution.models import Order, Trade
from marketdata.models import Instrument, PriceBar
from portfolio.models import Account, Position
from risk.models import RiskDecision
from strategies.models import Strategy

from .serializers import (
    AccountSerializer,
    InstrumentSerializer,
    OrderSerializer,
    PositionSerializer,
    PriceBarSerializer,
    RiskDecisionSerializer,
    StrategySerializer,
    TradeSerializer,
)


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
