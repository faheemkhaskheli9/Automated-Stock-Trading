# syntax=docker/dockerfile:1

# ---- builder: compile/install dependencies into an isolated prefix -----
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# build-essential + libpq-dev: needed to build psycopg from source on some
# platforms; harmless if the binary wheel is used instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- final: slim runtime image, no build toolchain ----------------------
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=AutomaticStockTrading.settings.prod \
    PATH="/usr/local/bin:$PATH"

# libpq5: psycopg's runtime dependency (not needed at build time only).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Placeholder env vars satisfy settings/prod.py's startup validation for this
# build-time-only step (no request ever gets served with them) - the real
# SECRET_KEY/ALLOWED_HOSTS come from the runtime environment (secret
# manager / orchestrator config), never baked into the image.
RUN SECRET_KEY=collectstatic-build-step-only-do-not-use ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "AutomaticStockTrading.wsgi:application", "--bind", "0.0.0.0:8000"]
