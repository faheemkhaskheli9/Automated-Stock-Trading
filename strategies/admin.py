from django.contrib import admin

from .models import ManualSignal, Strategy


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active", "updated_at")
    list_filter = ("key", "is_active")
    search_fields = ("name", "key")
    filter_horizontal = ("instruments",)


@admin.register(ManualSignal)
class ManualSignalAdmin(admin.ModelAdmin):
    list_display = ("instrument", "date", "action", "created_by", "created_at")
    list_filter = ("action",)
    search_fields = ("instrument__symbol",)
    autocomplete_fields = ("instrument",)
    date_hierarchy = "date"
