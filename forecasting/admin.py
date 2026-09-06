from django.contrib import admin

from .models import ForecastBacktestRun


@admin.register(ForecastBacktestRun)
class ForecastBacktestRunAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "predictor_key",
        "symbol",
        "scheme",
        "status",
        "skill_vs_naive",
        "looks_leaky",
        "started_at",
    )
    list_filter = ("status", "scheme", "predictor_key", "looks_leaky", "exchange")
    search_fields = ("name", "predictor_key", "symbol")
    readonly_fields = tuple(f.name for f in ForecastBacktestRun._meta.fields)

    def has_add_permission(self, request):
        # Runs are created by the service / command / task, never hand-built.
        return False
