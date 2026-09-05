from django.apps import AppConfig


class ModelingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "modeling"
    verbose_name = "Trading models"

    def ready(self):
        # Importing these fires each class's @register_estimator decorator.
        # Deferred to ready() (not the top of models.py) for the same reason
        # strategies does it - see strategies/apps.py. `deep` soft-imports
        # torch and simply registers nothing when the extra is absent.
        from . import deep, estimators  # noqa: F401
