---
name: add-operator-ui-page
description: Add a new page to the "PSX Observatory" server-rendered operator dashboard, matching its single token-based design system (no HTMX/Tailwind/build step). Use when asked to add a UI page, view, or dashboard panel to the trading app.
---

# Add an operator UI page

The whole dashboard ("PSX Observatory") is plain server-rendered Django —
function-based views + Django templates, **one** shared stylesheet, no
frontend framework, no build step. This is a deliberate, tested constraint
(project KB `conventions.md` → "Operator UI — one design system";
`marketdata/tests/test_ui_consistency.py` and `test_nav.py` enforce it). Do
not introduce HTMX, Tailwind, inline `<style>`, or a new per-app stylesheet —
past attempts at those were reverted.

## Steps

1. **View**: a plain FBV in the owning app's `views.py`, `@login_required`.
   If the data is per-owner (accounts, orders, watch items), scope the
   queryset the way `portfolio`/`execution`/`risk` do — `request.user`'s
   rows only, staff see all (`_scoped(request)` helper pattern).
   Staff-only actions (anything touching every account/model, like
   `run_cycle`) require `request.user.is_staff` and a `confirm=yes` POST
   param, per `execution.views.run_cycle`.
2. **Template**: `{% extends "marketdata/base.html" %}` under
   `<app>/templates/<app>/`. Use only the shared component classes already
   in `marketdata/static/marketdata/dashboard.css` — check it first:
   `.panel` / `.controls` / `.section-heading` / `.panel-title`, `.kpi`,
   `.stat` / `.stat-grid`, `.metric-cards .card`, `.action-row`,
   `.chip` + `.chip-pos/-neg/-neutral`, `.badge`, `.notice
   .error/.warning/.success`, `.field-row` + `.errorlist`, `.empty`,
   `.skill-badge`. **No `style="..."` and no `<style>` block** — the one
   sanctioned exception is view-computed overlay colours
   (`instrument_detail.html`'s pattern), and even that must stay a rare,
   justified case.
3. **Need a new visual element the stylesheet doesn't have?** Add the class
   to `dashboard.css` in its right section (tokens → base → layout/nav →
   components → page-specific → responsive) using the existing CSS custom
   properties — never a hardcoded hex — and add both a light and a
   `@media (prefers-color-scheme: dark)` rule.
4. **Charts**: reuse `{% include "marketdata/_linechart.html" %}` (params
   `aria`, `s1_points`, `s1_label`, `s2_points`, `s2_label`, `height`) for
   any predicted-vs-actual / equity-style polyline. Only build a bespoke SVG
   if the shape genuinely doesn't fit (candlestick, scatter) — and still use
   the token chart classes (`.chart-grid`, `.price-line`, ...).
5. **Long lists paginate**: wrap the queryset in
   `Paginator(qs, SIZE).get_page(request.GET.get(param or "page"))` and
   render `{% include "marketdata/_pagination.html" with page=<Page>
   query=<qs_minus_page> param=<name> %}`. Only pass `param` when one page
   hosts more than one pager. Pick `SIZE` as a module constant (25 wide
   rows / 50 terse rows, matching sibling views).
6. **Nav**: add the link inside `marketdata/templates/marketdata/base.html`'s
   `.mainnav`/`.navgroup` structure — but do not otherwise restructure that
   DOM; `marketdata/tests/test_nav.py` asserts it exactly, including the
   inline nav `<script>`.
7. **URLs**: wire into the owning app's `urls.py`, then `include()` it from
   `AutomaticStockTrading/urls.py` if it's a new app.
8. **Tests**: a view test (status code, owner-scoping if applicable,
   staff-gating if applicable) plus rely on the existing
   `test_ui_consistency.py` / `test_pagination.py` / `test_nav.py` running
   against the whole templates tree — don't duplicate their assertions, just
   don't violate them.

## Verify

```
.venv/Scripts/python.exe -m pytest marketdata -q   # UI consistency + nav + pagination guards
.venv/Scripts/python.exe -m pytest <your app> -q
black . && isort . && ruff check .
```
