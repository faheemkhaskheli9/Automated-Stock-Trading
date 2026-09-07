"""Read-only operator views over the risk audit trail (Phase 9 U6)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import DailyEquitySnapshot, RiskDecision

PAGE_SIZE = 50


def _scope(qs, request, path="account__owner"):
    if request.user.is_staff:
        return qs
    return qs.filter(**{path: request.user})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def decisions(request):
    qs = _scope(RiskDecision.objects.select_related("account", "instrument", "strategy"), request)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "risk/decisions.html", {"rows": page, "page": page})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def equity_snapshots(request):
    qs = _scope(DailyEquitySnapshot.objects.select_related("account").order_by("-date"), request)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "risk/equity_snapshots.html", {"rows": page, "page": page})
