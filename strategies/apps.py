from django.apps import AppConfig


class StrategiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "strategies"

    def ready(self):
        # Importing these fires each class's @register_strategy decorator.
        # Deferred to ready() (rather than the top of models.py) because
        # manual.py imports ManualSignal from .models - importing it while
        # models.py is still being evaluated would be circular.
        from . import manual, ml, rules  # noqa: F401
