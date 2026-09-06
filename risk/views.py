"""Read-only operator views over the risk audit trail (Phase 9 U6)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import DailyEquitySnapshot, RiskDecision


def _scope(qs, request, path="account__owner"):
    if request.user.is_staff:
        return qs
    return qs.filter(**{path: request.user})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def decisions(request):
    rows = _scope(
        RiskDecision.objects.select_related("account", "instrument", "strategy"), request
    )[:200]
    return render(request, "risk/decisions.html", {"rows": rows})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def equity_snapshots(request):
    rows = _scope(DailyEquitySnapshot.objects.select_related("account").order_by("-date"), request)[
        :200
    ]
    return render(request, "risk/equity_snapshots.html", {"rows": rows})
