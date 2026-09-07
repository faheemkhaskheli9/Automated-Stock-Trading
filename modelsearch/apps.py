from django.apps import AppConfig


class ModelsearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modelsearch"
    verbose_name = "Model search"

    # No ready() hook: this app has no registry of its own. It reuses the
    # estimator registry that ``modeling.apps.ModelingConfig.ready()`` populates.
