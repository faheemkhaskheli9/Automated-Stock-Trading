from django.contrib import admin

from .models import Account, Position


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "owner",
        "account_type",
        "broker",
        "cash_balance",
        "currency",
        "updated_at",
    )
    list_filter = ("account_type", "broker")
    search_fields = ("name", "owner__username")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("account", "instrument", "quantity", "avg_entry_price", "updated_at")
    search_fields = ("account__name", "instrument__symbol")
    autocomplete_fields = ("instrument",)
