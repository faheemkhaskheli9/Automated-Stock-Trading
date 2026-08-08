from django.contrib import admin

from .models import Order, Trade


class TradeInline(admin.TabularInline):
    model = Trade
    extra = 0
    readonly_fields = ("quantity", "price", "executed_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "instrument",
        "side",
        "quantity",
        "status",
        "filled_price",
        "strategy",
        "created_at",
    )
    list_filter = ("status", "side")
    search_fields = ("account__name", "instrument__symbol", "broker_order_id")
    autocomplete_fields = ("instrument",)
    inlines = [TradeInline]


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("order", "quantity", "price", "executed_at")
    date_hierarchy = "executed_at"
