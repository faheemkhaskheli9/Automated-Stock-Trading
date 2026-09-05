from django.contrib import admin

from .models import ModelPrediction, ModelTrainingRun, TradingModel


@admin.register(TradingModel)
class TradingModelAdmin(admin.ModelAdmin):
    list_display = ("name", "estimator_key", "is_active", "trained_at", "updated_at")
    list_filter = ("estimator_key", "is_active")
    search_fields = ("name", "estimator_key")
    filter_horizontal = ("instruments",)
    readonly_fields = ("artifact_path", "metrics", "trained_at", "created_at", "updated_at")


@admin.register(ModelTrainingRun)
class ModelTrainingRunAdmin(admin.ModelAdmin):
    list_display = ("model", "status", "started_at", "finished_at", "rows", "feature_count")
    list_filter = ("status", "model")
    readonly_fields = tuple(f.name for f in ModelTrainingRun._meta.fields)


@admin.register(ModelPrediction)
class ModelPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "model",
        "instrument",
        "target_date",
        "predicted_value",
        "actual_value",
        "abs_error",
    )
    list_filter = ("model", "instrument")
    date_hierarchy = "target_date"
    readonly_fields = tuple(f.name for f in ModelPrediction._meta.fields)
