from django.contrib import admin

from .models import ModelSearch, ModelSearchResult, ModelSearchRun


@admin.register(ModelSearch)
class ModelSearchAdmin(admin.ModelAdmin):
    list_display = ("name", "mode", "max_candidates", "scoring", "updated_at")
    list_filter = ("mode",)
    search_fields = ("name",)
    filter_horizontal = ("instruments",)
    readonly_fields = ("best_result", "created_at", "updated_at")


@admin.register(ModelSearchRun)
class ModelSearchRunAdmin(admin.ModelAdmin):
    list_display = (
        "search",
        "status",
        "started_at",
        "finished_at",
        "candidates_ok",
        "candidates_failed",
    )
    list_filter = ("status", "search")
    readonly_fields = tuple(f.name for f in ModelSearchRun._meta.fields)


@admin.register(ModelSearchResult)
class ModelSearchResultAdmin(admin.ModelAdmin):
    list_display = (
        "run",
        "estimator_key",
        "rank",
        "score",
        "fit_seconds",
        "predict_latency_ms",
        "model_size_bytes",
        "is_pareto",
        "status",
    )
    list_filter = ("status", "is_pareto", "estimator_key", "search")
    readonly_fields = tuple(f.name for f in ModelSearchResult._meta.fields)
