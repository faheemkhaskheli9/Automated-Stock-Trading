# Phase 8 - Weekly signal delivery (`signalfeed`)

Goal: on Monday, get a plain-language call on each watched ticker - will
Friday's close be up or down, and roughly how much - pushed to phone / inbox,
with a running track record so it can be trusted before real money.

Built on what already existed: the `modeling` studio's `weekday_anchored`
target (Mon entry -> Fri exit), `ModelPrediction` persistence + actual
backfill, the accuracy leaderboard, and `execution.notifications`.

## Status

All six steps landed as the `signalfeed` app (routed at `/signals/`). Nothing
is scheduled yet - the tasks are plain management commands meant for a cloud
scheduler (see Deployment).

| Step | What | State |
|---|---|---|
| S1 | `WatchItem` model (instrument + model + accuracy bar) + admin | done |
| S2 | `train_weekly_models` + `gate.evaluate_gate` (leaderboard, holdout fallback) | done |
| S3 | `services.generate_weekly_signals` - forecast -> `WeeklySignal` (direction + magnitude) | done |
| S4 | `delivery.deliver` - email / webhook / Telegram; `execution.notifications` refactor + Telegram sender | done |
| S5 | `send_weekly_signals` / `recap_weekly_signals` commands + tasks; Friday grading + hit-rate recap | done |
| S6 | `/signals/` page (this week + trailing hit-rate + recent) + minimal web manifest | done |
| U1 | `/signals/watchlist/` CRUD + `/signals/` action bar (generate / send / train / recap, run synchronously) - no more admin/CLI needed for routine use | done |

## How to run it

From the UI (preferred, since U1): configure a weekly model in `/modeling/`
(target `weekday_anchored`, entry 0 / exit 4, instruments, active), add rows at
`/signals/watchlist/`, then use the action bar on `/signals/` -
**Generate (no send)** / **Generate & send** / **Train watchlist models** /
**Run recap**. Each runs synchronously and reports a summary message.

Equivalent management commands (still used by the cloud scheduler):

```
python manage.py train_weekly_models
python manage.py send_weekly_signals --dry-run     # inspect, no send
python manage.py send_weekly_signals               # build + push
python manage.py recap_weekly_signals              # Friday: grade + recap
```

Delivery channels (all optional, all reused by order alerts too):
`ADMIN_EMAILS`, `ALERT_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`.
With none set, signals are generated and logged but not delivered.

## The accuracy gate (S2)

A `WeeklySignal` is only delivered if its model clears the watch item's bar:
`min_directional_accuracy` (trailing out-of-sample up/down hit-rate) and
optionally `min_skill` (skill-vs-naive). Numbers come from the live
`modeling` leaderboard when there are enough backfilled predictions, else the
model's last-training holdout metrics. A model that misses the bar still gets
a stored `suppressed` signal with the reason - visible in admin and on
`/signals/`, just not pushed.

## Scheduling (Deployment)

Wire the three tasks to a cloud managed scheduler, Asia/Karachi:
- `train_weekly_models_task` - weekly (e.g. Sunday)
- `send_weekly_signals_task` - Monday pre-open (~08:30)
- `recap_weekly_signals_task` - Friday post-close (~17:00)

## Honest expectations

Weekly direction of a single stock is close to a coin flip. A model that
genuinely holds 54-57% out-of-sample is a good result. Magnitude estimates
have error bars wider than the estimate. Run advisory-only for at least a
quarter and watch the recap hit-rate before trading on it; when you do,
sizing and loss limits still go through the `risk` app.

## Not done / deferred

- No service worker / offline PWA support (manifest only).
- No auto-execution path (deliberate - advisory only).
- No per-signal position sizing.
- Telegram is one-recipient (single `TELEGRAM_CHAT_ID`), not multi-user.
