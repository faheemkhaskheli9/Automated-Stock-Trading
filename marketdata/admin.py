from django.contrib import admin

from .models import Instrument, PriceBar


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "exchange", "sector", "is_active", "updated_at")
    list_filter = ("exchange", "sector", "is_active")
    search_fields = ("symbol", "name")


@admin.register(PriceBar)
class PriceBarAdmin(admin.ModelAdmin):
    list_display = (
        "instrument",
        "timeframe",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_anomaly",
    )
    list_filter = ("timeframe", "is_anomaly")
    search_fields = ("instrument__symbol",)
    date_hierarchy = "timestamp"
    autocomplete_fields = ("instrument",)
