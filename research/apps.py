from django.apps import AppConfig


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "research"

    def ready(self):
        # Import concrete providers so their @register_feature_provider
        # decorators populate the registry. Deferred to ready() for the same
        # reason strategies/apps.py does it: provider modules import models.
        from .providers import fundamentals, news, social, technical  # noqa: F401
