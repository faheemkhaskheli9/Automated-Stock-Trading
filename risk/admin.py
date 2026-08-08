from django.contrib import admin

from .models import DailyEquitySnapshot, RiskDecision


@admin.register(RiskDecision)
class RiskDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "account",
        "instrument",
        "action",
        "quantity",
        "approved",
        "reason",
        "created_at",
    )
    list_filter = ("approved", "action")
    search_fields = ("account__name", "instrument__symbol")
    date_hierarchy = "created_at"


@admin.register(DailyEquitySnapshot)
class DailyEquitySnapshotAdmin(admin.ModelAdmin):
    list_display = ("account", "date", "opening_equity")
    list_filter = ("date",)
