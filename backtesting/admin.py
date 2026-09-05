from django.contrib import admin

from .models import (
    Backtest,
    BacktestFold,
    BacktestPrediction,
    BacktestRun,
    BacktestTrade,
)


@admin.register(Backtest)
class BacktestAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "model",
        "fit_mode",
        "scheme",
        "train_span",
        "test_span",
        "step",
        "is_active",
    )
    list_filter = ("fit_mode", "scheme", "is_active", "model")
    search_fields = ("name", "model__name")
    raw_id_fields = ("training_run",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(BacktestRun)
class BacktestRunAdmin(admin.ModelAdmin):
    list_display = ("backtest", "status", "started_at", "n_folds", "n_predictions", "n_trades")
    list_filter = ("status", "backtest")
    readonly_fields = tuple(f.name for f in BacktestRun._meta.fields)


@admin.register(BacktestFold)
class BacktestFoldAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "fold_index",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "n_train",
        "n_test",
    )
    list_filter = ("run",)
    readonly_fields = tuple(f.name for f in BacktestFold._meta.fields)


@admin.register(BacktestPrediction)
class BacktestPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "instrument",
        "target_date",
        "predicted_value",
        "actual_value",
        "abs_error",
        "position",
    )
    list_filter = ("run", "instrument")
    date_hierarchy = "target_date"
    readonly_fields = tuple(f.name for f in BacktestPrediction._meta.fields)


@admin.register(BacktestTrade)
class BacktestTradeAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "instrument",
        "direction",
        "entry_date",
        "exit_date",
        "pnl",
        "return_pct",
    )
    list_filter = ("run", "instrument", "direction")
    readonly_fields = tuple(f.name for f in BacktestTrade._meta.fields)
