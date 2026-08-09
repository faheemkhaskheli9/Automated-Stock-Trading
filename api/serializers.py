from rest_framework import serializers

from execution.models import Order, Trade
from marketdata.models import Instrument, PriceBar
from portfolio.models import Account, Position
from risk.models import RiskDecision
from strategies.models import Strategy


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ["id", "symbol", "name", "exchange", "sector", "is_active"]


class PriceBarSerializer(serializers.ModelSerializer):
    instrument = serializers.SlugRelatedField(slug_field="symbol", read_only=True)

    class Meta:
        model = PriceBar
        fields = [
            "id",
            "instrument",
            "timeframe",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "is_anomaly",
        ]


class StrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = Strategy
        fields = [
            "id",
            "name",
            "key",
            "params",
            "instruments",
            "account",
            "is_active",
            "updated_at",
        ]
        # Everything but is_active is set up out-of-band (admin/shell) for now - the API's
        # job here is the "strategy on/off toggle" from docs/PLAN.md, Phase 4, not full CRUD.
        read_only_fields = ["name", "key", "params", "instruments", "account", "updated_at"]


class AccountSerializer(serializers.ModelSerializer):
    equity = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = Account
        fields = [
            "id",
            "name",
            "account_type",
            "broker",
            "currency",
            "cash_balance",
            "equity",
            "updated_at",
        ]
        read_only_fields = fields


class PositionSerializer(serializers.ModelSerializer):
    instrument = serializers.SlugRelatedField(slug_field="symbol", read_only=True)
    market_value = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    unrealized_pnl = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "id",
            "account",
            "instrument",
            "quantity",
            "avg_entry_price",
            "market_value",
            "unrealized_pnl",
        ]
        read_only_fields = fields

    def get_unrealized_pnl(self, obj: Position):
        return obj.market_value - (obj.avg_entry_price * obj.quantity)


class TradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trade
        fields = ["id", "order", "quantity", "price", "executed_at"]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    instrument = serializers.SlugRelatedField(slug_field="symbol", read_only=True)
    trades = TradeSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "account",
            "instrument",
            "strategy",
            "side",
            "quantity",
            "status",
            "filled_quantity",
            "filled_price",
            "rejection_reason",
            "submitted_at",
            "filled_at",
            "created_at",
            "trades",
        ]
        read_only_fields = fields


class RiskDecisionSerializer(serializers.ModelSerializer):
    instrument = serializers.SlugRelatedField(slug_field="symbol", read_only=True)

    class Meta:
        model = RiskDecision
        fields = [
            "id",
            "account",
            "instrument",
            "strategy",
            "action",
            "quantity",
            "approved",
            "reason",
            "created_at",
        ]
        read_only_fields = fields
