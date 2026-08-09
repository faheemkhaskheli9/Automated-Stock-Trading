from django.core.management.base import BaseCommand

from execution.tasks import run_trading_cycle


class Command(BaseCommand):
    help = (
        "Run one trading cycle synchronously, in this process - no Celery worker/broker "
        "required. Meant to be invoked directly by a managed scheduler (e.g. AWS EventBridge "
        "Scheduler running an ECS task, or GCP Cloud Scheduler triggering a Cloud Run Job) as "
        "an alternative to a persistent Celery beat process - see docs/DEPLOYMENT.md."
    )

    def handle(self, *args, **options):
        order_ids = run_trading_cycle()
        if not order_ids:
            self.stdout.write("Trading cycle complete: no orders placed.")
            return
        self.stdout.write(
            self.style.SUCCESS(f"Trading cycle complete: {len(order_ids)} order(s) placed.")
        )
        for order_id in order_ids:
            self.stdout.write(f"  order #{order_id}")
