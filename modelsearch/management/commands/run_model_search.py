"""Run a configured :class:`~modelsearch.models.ModelSearch` from the CLI.

    python manage.py run_model_search <search_id> [--seed N] [--max N]

Shares the code path (``modelsearch.services.run_search``) with the Celery
task and the UI's "Run search" button.
"""

from django.core.management.base import BaseCommand, CommandError

from modelsearch.models import ModelSearch
from modelsearch.services import run_search


class Command(BaseCommand):
    help = "Evaluate every candidate in a ModelSearch and print the ranking."

    def add_arguments(self, parser):
        parser.add_argument("search_id", type=int)
        parser.add_argument("--seed", type=int, default=None, help="Override random_seed.")
        parser.add_argument("--max", type=int, default=None, help="Override max_candidates.")

    def handle(self, *args, **options):
        search = ModelSearch.objects.filter(pk=options["search_id"]).first()
        if search is None:
            raise CommandError(f"No ModelSearch with id {options['search_id']}")

        dirty = []
        if options["seed"] is not None:
            search.random_seed = options["seed"]
            dirty.append("random_seed")
        if options["max"] is not None:
            search.max_candidates = options["max"]
            dirty.append("max_candidates")
        if dirty:
            search.save(update_fields=dirty)

        run = run_search(search)
        if run.status != run.Status.SUCCESS:
            raise CommandError(f"Search failed: {run.error}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Run #{run.pk}: {run.candidates_ok}/{run.candidates_total} scored "
                f"on {run.dataset_rows} rows, {run.feature_count} features."
            )
        )
        top = run.results.filter(status="ok").order_by("rank")[:5]
        for r in top:
            flag = " [pareto]" if r.is_pareto else ""
            self.stdout.write(
                f"  #{r.rank} {r.estimator_key} {r.estimator_params} "
                f"score={r.score:.4f} fit={r.fit_seconds:.3f}s "
                f"predict={r.predict_latency_ms:.3f}ms/row size={r.model_size_bytes}B{flag}"
            )
