"""Production settings. Requires real environment configuration - fails
loudly rather than silently falling back to insecure dev defaults."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

if not ALLOWED_HOSTS:
    raise ValueError("ALLOWED_HOSTS must be set via env in production.")

_secret_key = env("SECRET_KEY", default=None)
if not _secret_key or _secret_key.startswith("django-insecure-"):
    raise ValueError("SECRET_KEY must be set to a real secret via env in production.")
SECRET_KEY = _secret_key

# HTTPS/security hardening - safe to relax individual flags via env if the
# deployment terminates TLS somewhere Django can't see (e.g. behind a
# load balancer that already enforces it), but secure-by-default here.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Real email delivery for alerts (see notifications.py) - defaults to SMTP;
# override EMAIL_BACKEND via env if using a provider's API-based backend instead.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
