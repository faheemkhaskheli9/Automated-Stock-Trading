from rest_framework import serializers

from backtesting.models import Backtest, BacktestRun
from execution.models import Order, Trade
from marketdata.models import Instrument, PriceBar
from modeling.models import ModelPrediction, TradingModel
from portfolio.models import Account, Position
from research.models import NewsItem, ResearchSnapshot
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


# --- Phase 7: research / forecasting read API -------------------------------
#
# These models are operator-global configuration and reference data (no
# per-user Account scoping), so the viewsets are plain authenticated reads.
# TradingModel mirrors StrategySerializer: only the on/off toggle is writable.


class NewsItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsItem
        fields = [
            "id",
            "symbol",
            "exchange",
            "headline",
            "url",
            "source",
            "published_at",
            "sentiment",
            "ingested_at",
        ]
        read_only_fields = fields


class ResearchSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResearchSnapshot
        fields = [
            "id",
            "symbol",
            "exchange",
            "as_of",
            "features",
            "sources",
            "provider_keys",
            "built_at",
        ]
        read_only_fields = fields


class TradingModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradingModel
        fields = [
            "id",
            "name",
            "estimator_key",
            "estimator_params",
            "feature_spec",
            "target_spec",
            "instruments",
            "train_start",
            "train_end",
            "is_active",
            "artifact_path",
            "metrics",
            "trained_at",
            "updated_at",
        ]
        # Same contract as StrategySerializer - configuration is set up
        # out-of-band (admin/commands); the API only flips is_active.
        read_only_fields = [f for f in fields if f != "is_active"]


class ModelPredictionSerializer(serializers.ModelSerializer):
    model = serializers.SlugRelatedField(slug_field="name", read_only=True)
    instrument = serializers.SlugRelatedField(slug_field="symbol", read_only=True)

    class Meta:
        model = ModelPrediction
        fields = [
            "id",
            "model",
            "instrument",
            "as_of",
            "target_date",
            "predicted_value",
            "predicted_json",
            "actual_value",
            "abs_error",
            "created_at",
        ]
        read_only_fields = fields


class BacktestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = BacktestRun
        fields = [
            "id",
            "backtest",
            "status",
            "started_at",
            "finished_at",
            "n_folds",
            "n_predictions",
            "n_trades",
            "metrics",
            "equity_curve",
            "error",
        ]
        read_only_fields = fields


class BacktestSerializer(serializers.ModelSerializer):
    model = serializers.SlugRelatedField(slug_field="name", read_only=True)
    runs = BacktestRunSerializer(many=True, read_only=True)

    class Meta:
        model = Backtest
        fields = [
            "id",
            "name",
            "model",
            "fit_mode",
            "scheme",
            "train_span",
            "test_span",
            "step",
            "gap",
            "start",
            "end",
            "long_threshold",
            "allow_short",
            "initial_cash",
            "commission_bps",
            "slippage_bps",
            "is_active",
            "updated_at",
            "runs",
        ]
        read_only_fields = fields
