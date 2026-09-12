"""Operator UI for paper trading (Phase 9 U5).

Read views over `Order` / `Trade`, plus two POST actions that go through the
exact same code path as the scheduler:

- `place_order` -> `execution.services.place_order` (duplicate guard ->
  `risk.engine.evaluate` -> `PaperBroker`).
- `run_cycle` -> `execution.tasks.run_trading_cycle` (staff only - it acts on
  every active strategy across all accounts).

Paper broker only. There is no live-broker path (Phase 6, gated).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from AutomaticStockTrading.scoping import scope_to_owner
from portfolio.models import Account
from risk.models import RiskDecision
from strategies.signals import Action

from .forms import PlaceOrderForm
from .models import Order
from .services import place_order as place_order_service
from .tasks import run_trading_cycle

logger = logging.getLogger(__name__)

ORDER_PAGE_SIZE = 50


def _scoped_orders(request):
    qs = Order.objects.select_related("account", "instrument", "strategy")
    return scope_to_owner(qs, request, owner_lookup="account__owner")


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def order_list(request):
    orders = _scoped_orders(request)
    status = request.GET.get("status")
    if status in Order.Status.values:
        orders = orders.filter(status=status)
    page = Paginator(orders, ORDER_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "execution/order_list.html",
        {
            "orders": page,
            "page": page,
            "query": urlencode({"status": status}) if status in Order.Status.values else "",
            "status": status or "",
            "statuses": Order.Status.choices,
            "can_run_cycle": request.user.is_staff,
        },
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET"])
def order_detail(request, pk):
    order = get_object_or_404(_scoped_orders(request), pk=pk)
    decisions = RiskDecision.objects.filter(
        account=order.account, instrument=order.instrument
    ).order_by("-created_at")[:5]
    return render(
        request,
        "execution/order_detail.html",
        {"order": order, "trades": order.trades.all(), "decisions": decisions},
    )


@login_required(login_url="marketdata:login")
@require_http_methods(["GET", "POST"])
def place_order(request):
    form = PlaceOrderForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        account = data["account"]
        if account.broker != Account.Broker.PAPER:
            form.add_error("account", "Only paper accounts can be traded from here.")
        else:
            try:
                order = place_order_service(
                    account, data["instrument"], Action(data["side"]), data["quantity"]
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the operator
                logger.exception("manual place_order failed")
                form.add_error(None, f"Could not place the order: {exc}")
            else:
                if order.status == Order.Status.FILLED:
                    messages.success(request, f"Order #{order.pk} filled at {order.filled_price}.")
                elif order.status == Order.Status.REJECTED:
                    messages.warning(
                        request, f"Order #{order.pk} rejected: {order.rejection_reason}"
                    )
                else:
                    messages.info(request, f"Order #{order.pk} is {order.get_status_display()}.")
                return redirect("execution:order_detail", pk=order.pk)
    return render(request, "execution/place_order.html", {"form": form})


@login_required(login_url="marketdata:login")
@require_http_methods(["POST"])
def run_cycle(request):
    if not request.user.is_staff:
        messages.error(request, "Running the trading cycle is a staff-only action.")
        return redirect("execution:order_list")
    if request.POST.get("confirm") != "yes":
        messages.error(request, "Confirmation required.")
        return redirect("execution:order_list")
    try:
        order_ids = run_trading_cycle()
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_trading_cycle failed")
        messages.error(request, f"Trading cycle failed: {exc}")
    else:
        messages.success(
            request, f"Trading cycle placed {len(order_ids)} order(s): {order_ids or 'none'}."
        )
    return redirect("execution:order_list")
