"""Operator UI for accounts & positions (Phase 9 U4).

Owner-scoped: a user sees only their own `Account`s; staff see all. No
trading happens here - that is the `execution` UI (U5).
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from AutomaticStockTrading.scoping import scope_to_owner

from .forms import AccountForm
from .models import Account

ACCOUNT_PAGE_SIZE = 25


def _scoped(request):
    return scope_to_owner(Account.objects.all(), request, owner_lookup="owner")


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def account_list(request):
    accounts = _scoped(request).select_related("owner").prefetch_related("positions")
    page = Paginator(accounts, ACCOUNT_PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {
            "obj": a,
            "equity": a.equity,
            # len() on the prefetched queryset avoids a per-account COUNT(*).
            "positions": len(a.positions.all()),
        }
        for a in page
    ]
    return render(request, "portfolio/account_list.html", {"rows": rows, "page": page})


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
    # Validate the name-uniqueness check against the account's actual owner
    # (not the logged-in staff user) when a staff user edits someone else's
    # account.
    owner = instance.owner if instance else request.user
    form = AccountForm(request.POST or None, instance=instance, owner=owner)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if obj.owner_id is None:
            obj.owner = request.user
        obj.save()
        messages.success(request, f"Saved account '{obj.name}'.")
        return redirect("portfolio:account_detail", pk=obj.pk)
    return render(request, "portfolio/account_form.html", {"form": form, "instance": instance})
