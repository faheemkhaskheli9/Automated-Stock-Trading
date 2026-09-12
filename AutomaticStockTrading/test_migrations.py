"""Guards against the class of bug behind the 2026-09-07 `/modeling/new/` 500:
IntegrityError on ``modeling_tradingmodel.exclude_anomalies``.

Root cause: a feature branch added ``TradingModel.exclude_anomalies`` +
migration ``0002_tradingmodel_exclude_anomalies``, applied it to the shared
local ``db.sqlite3``, then the tree switched back to ``main`` - which has
neither the field nor the migration file. The column (NOT NULL, no SQL-level
default) and the ``django_migrations`` row survived the branch switch, so
`main`'s ORM inserts (which don't know the column exists) started failing.

``makemigrations --check`` (also run in CI, see .github/workflows/ci.yml)
catches the *model vs. migration files* half of that drift on every run -
i.e. a model field with no migration, or vice versa. It runs against this
test's own migrated test database, so it can't see a stale *local* sqlite
file left over from switching branches; run
``python manage.py check_db_drift`` after switching branches for that half.
"""

import pytest
from django.core.management import call_command

# makemigrations checks the DB's applied-migrations history for consistency
# (django.db.migrations.loader.MigrationLoader.check_consistent_history), so
# it needs a real connection even though it writes nothing.
pytestmark = pytest.mark.django_db


def test_no_missing_migrations():
    """Every model field must be backed by a migration, and vice versa.

    Fails the way ``makemigrations`` would if it had something to write -
    i.e. the app's migrations don't fully describe its models.
    """
    call_command("makemigrations", "--check", "--dry-run")
