"""Detect schema drift between the live database and the current models.

Exists because of a real incident: a feature branch added a model field +
migration, applied the migration to the shared local ``db.sqlite3``, then the
tree switched back to ``main`` (which has neither) - the column and the
``django_migrations`` row survived the branch switch, and ``main``'s ORM
inserts started failing with an ``IntegrityError`` the moment they hit that
NOT NULL column. See ``modeling.models.TradingModel`` / git history around
2026-09-07 for the incident.

``python manage.py makemigrations --check`` (run in CI on every push) catches
the *model vs. migration files* half of this - it would have flagged the
missing migration if this had reached ``main``. It runs against a freshly
migrated database, so it can never see this half: a *local* database that
carries schema from a migration file no longer on disk. Run this command
after switching branches (or whenever ``/modeling/new/``-style IntegrityErrors
look like a NOT NULL/missing-column mismatch) to catch that instead.
"""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Compare live DB columns/migration rows against the current models "
        "for every local app; report drift left over from switching "
        "branches without re-migrating."
    )

    def handle(self, *args, **options):
        problems = []
        problems.extend(self._check_columns())
        problems.extend(self._check_ghost_migrations())

        if not problems:
            self.stdout.write(self.style.SUCCESS("No schema drift detected."))
            return

        for line in problems:
            self.stderr.write(self.style.ERROR(line))
        raise SystemExit(1)

    def _local_app_labels(self):
        # Apps whose migrations live in this repo (not third-party/contrib) -
        # i.e. everything except django.contrib.* and the two pip-installed
        # apps in INSTALLED_APPS (see AutomaticStockTrading/settings/base.py).
        third_party = {"rest_framework", "django_celery_beat"}
        return {
            cfg.label
            for cfg in apps.get_app_configs()
            if not cfg.name.startswith("django.") and cfg.name not in third_party
        }

    def _check_columns(self):
        problems = []
        local_apps = self._local_app_labels()
        with connection.cursor() as cursor:
            existing_tables = set(connection.introspection.table_names(cursor))
            for model in apps.get_models():
                if model._meta.app_label not in local_apps:
                    continue
                table = model._meta.db_table
                if table not in existing_tables:
                    continue
                db_columns = {
                    col.name for col in connection.introspection.get_table_description(
                        cursor, table
                    )
                }
                model_columns = {f.column for f in model._meta.local_fields}
                extra = sorted(db_columns - model_columns)
                missing = sorted(model_columns - db_columns)
                if extra:
                    problems.append(
                        f"{table}: DB has column(s) not on the model (stale migration "
                        f"applied on a branch that was since abandoned?): {extra}"
                    )
                if missing:
                    problems.append(
                        f"{table}: model has field(s) with no DB column (migration not "
                        f"applied - run `manage.py migrate`?): {missing}"
                    )
        return problems

    def _check_ghost_migrations(self):
        problems = []
        local_apps = self._local_app_labels()
        with connection.cursor() as cursor:
            if "django_migrations" not in connection.introspection.table_names(cursor):
                return problems
            cursor.execute("SELECT app, name FROM django_migrations")
            recorded = list(cursor.fetchall())

        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(connection, ignore_no_migrations=True)
        for app, name in recorded:
            if app not in local_apps:
                continue
            if (app, name) not in loader.disk_migrations:
                problems.append(
                    f"{app}: migration '{name}' is recorded as applied but has no file on "
                    "disk (left over from a deleted/rebased migration - see the module "
                    "docstring for the fix)."
                )
        return problems
