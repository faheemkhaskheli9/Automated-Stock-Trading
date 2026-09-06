"""Operator UI for accounts & positions (Phase 9 U4).

Owner-scoped: a user sees only their own `Account`s; staff see all. No
trading happens here - that is the `execution` UI (U5).
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import AccountForm
from .models import Account


def _scoped(request):
    qs = Account.objects.all()
    if not request.user.is_staff:
        qs = qs.filter(owner=request.user)
    return qs


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def account_list(request):
    accounts = _scoped(request).select_related("owner").prefetch_related("positions")
    rows = [
        {
            "obj": a,
            "equity": a.equity,
            "positions": a.positions.count(),
        }
        for a in accounts
    ]
    return render(request, "portfolio/account_list.html", {"rows": rows})


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def account_detail(request, pk):
    account = get_object_or_404(_scoped(request), pk=pk)
    positions = []
    for p in account.positions.select_related("instrument"):
        cost = p.avg_entry_price * p.quantity
        positions.append(
            {
                "obj": p,
                "market_value": p.market_value,
                "cost": cost,
                "unrealized_pnl": p.market_value - cost,
            }
        )
    return render(
        request,
        "portfolio/account_detail.html",
        {
            "account": account,
            "positions": positions,
            "equity": account.equity,
            "invested": sum((r["market_value"] for r in positions), Decimal("0")),
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def account_edit(request, pk=None):
    instance = get_object_or_404(_scoped(request), pk=pk) if pk else None
    form = AccountForm(request.POST or None, instance=instance, owner=request.user)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if obj.owner_id is None:
            obj.owner = request.user
        obj.save()
        messages.success(request, f"Saved account '{obj.name}'.")
        return redirect("portfolio:account_detail", pk=obj.pk)
    return render(request, "portfolio/account_form.html", {"form": form, "instance": instance})
