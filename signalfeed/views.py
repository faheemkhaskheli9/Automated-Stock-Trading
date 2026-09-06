import logging
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import services
from .forms import WatchItemForm
from .gate import evaluate_gate
from .models import WatchItem, WeeklySignal

logger = logging.getLogger(__name__)

ACCURACY_WINDOW_DAYS = 90
_RUN_ACTIONS = {"generate", "send", "train", "recap"}


def _parse_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def index(request):
    """Latest week's calls + a trailing hit-rate + the action bar. Mobile-
    friendly: the page links a web manifest so it can be added to a phone
    home screen."""
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


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def watchlist(request):
    """Every watch item + its model's live gate verdict."""
    items = WatchItem.objects.select_related("instrument", "trading_model")
    rows = [(item, evaluate_gate(item)) for item in items]
    return render(request, "signalfeed/watchlist.html", {"rows": rows})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def watch_edit(request, pk=None):
    instance = get_object_or_404(WatchItem, pk=pk) if pk else None
    form = WatchItemForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        messages.success(request, f"Saved watch item: {obj}.")
        return redirect("signalfeed:watchlist")
    return render(request, "signalfeed/watch_form.html", {"form": form, "instance": instance})


@login_required(login_url="marketdata:login")
@require_http_methods(["POST"])
def watch_delete(request, pk):
    """Soft delete - deactivate the watch item, keeping its signal history."""
    item = get_object_or_404(WatchItem, pk=pk)
    item.is_active = False
    item.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Deactivated {item}.")
    return redirect("signalfeed:watchlist")


@login_required(login_url="marketdata:login")
@require_http_methods(["POST"])
def run(request):
    """Trigger a signalfeed batch job synchronously from the UI."""
    action = request.POST.get("action", "")
    if action not in _RUN_ACTIONS:
        messages.error(request, f"Unknown action {action!r}.")
        return redirect("signalfeed:index")

    as_of = _parse_date(request.POST.get("as_of"))
    include_flat = bool(request.POST.get("include_flat"))
    try:
        if action == "train":
            runs = services.train_weekly_models()
            ok = sum(1 for r in runs if r.status == r.Status.SUCCESS)
            messages.success(request, f"Trained {len(runs)} model(s); {ok} succeeded.")
        elif action == "recap":
            s = services.recap_weekly_signals(as_of=as_of)
            messages.success(
                request,
                f"Recap: graded {s['scored_now']}, week {s['week_hits']}/{s['week_total']} correct, "
                f"delivered to {', '.join(s['delivered_to']) or 'nobody'}.",
            )
        else:  # generate / send
            dry_run = action == "generate"
            s = services.send_weekly_signals(
                as_of=as_of, dry_run=dry_run, include_flat=include_flat
            )
            verb = "Generated" if dry_run else "Sent"
            messages.success(
                request,
                f"{verb}: {s['generated']} built, {s['sent']} sent, {s['suppressed']} suppressed, "
                f"{s['flat']} flat, {s['errors']} error(s).",
            )
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        logger.exception("signalfeed run action %s failed", action)
        messages.error(request, f"{action} failed: {exc}")
    return redirect("signalfeed:index")


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
