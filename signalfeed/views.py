from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import WatchItem, WeeklySignal

ACCURACY_WINDOW_DAYS = 90


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    """Latest week's calls + a trailing hit-rate. Mobile-friendly: the page
    links a web manifest so it can be added to a phone home screen."""
    today = timezone.localdate()
    signals = list(
        WeeklySignal.objects.select_related("instrument", "trading_model").order_by(
            "-target_date", "instrument__symbol"
        )[:100]
    )
    latest_target = signals[0].target_date if signals else None
    current = [s for s in signals if s.target_date == latest_target] if latest_target else []

    graded = WeeklySignal.objects.filter(
        was_correct__isnull=False,
        status=WeeklySignal.Status.SENT,
        target_date__gte=today - timedelta(days=ACCURACY_WINDOW_DAYS),
    )
    total = graded.count()
    hits = graded.filter(was_correct=True).count()

    return render(
        request,
        "signalfeed/index.html",
        {
            "current": current,
            "latest_target": latest_target,
            "recent": signals,
            "watch_count": WatchItem.objects.filter(is_active=True).count(),
            "window_days": ACCURACY_WINDOW_DAYS,
            "hit_total": total,
            "hit_count": hits,
            "hit_rate": (hits / total) if total else None,
        },
    )


@require_http_methods(["GET"])
def manifest(request):
    """Minimal PWA manifest so the signals page can be 'added to home screen'.
    No service worker / offline support yet - that is deferred."""
    return JsonResponse(
        {
            "name": "PSX Weekly Signals",
            "short_name": "PSX Signals",
            "start_url": "/signals/",
            "display": "standalone",
            "background_color": "#0f1216",
            "theme_color": "#0f1216",
            "icons": [],
        },
        content_type="application/manifest+json",
    )
