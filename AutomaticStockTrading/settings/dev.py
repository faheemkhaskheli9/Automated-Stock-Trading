"""Local development settings. Not for use in production."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

# Convenient for local dev regardless of ALLOWED_HOSTS env var.
ALLOWED_HOSTS = list(set(env.list("ALLOWED_HOSTS", default=[]) + ["localhost", "127.0.0.1"]))

# Print alert emails to the console instead of sending anything real.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
