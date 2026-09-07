from django.contrib import admin

from .models import WatchItem, WeeklySignal


@admin.register(WatchItem)
class WatchItemAdmin(admin.ModelAdmin):
    list_display = (
        "instrument",
        "trading_model",
        "is_active",
        "min_directional_accuracy",
        "min_skill",
        "min_expected_move_pct",
        "sizing_capital",
    )
    list_filter = ("is_active", "trading_model")
    search_fields = ("instrument__symbol", "trading_model__name")
    autocomplete_fields = ("instrument", "trading_model")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WeeklySignal)
class WeeklySignalAdmin(admin.ModelAdmin):
    list_display = (
        "instrument",
        "target_date",
        "direction",
        "expected_return_pct",
        "suggested_shares",
        "status",
        "was_correct",
        "actual_return_pct",
        "sent_at",
    )
    list_filter = ("status", "direction", "was_correct", "trading_model")
    search_fields = ("instrument__symbol",)
    date_hierarchy = "target_date"
    readonly_fields = tuple(f.name for f in WeeklySignal._meta.fields)
