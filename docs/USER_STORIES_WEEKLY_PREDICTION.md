# User stories - weekly (Mon->Fri) price prediction & notification

Scope: predict Friday's close from data available up to Monday, notify the
user of direction + expected magnitude, back-test the approach for accuracy,
and check each prediction against the real Friday close once it arrives.

This capability is **already largely implemented** across `modeling`
(`weekday_anchored` target), `forecasting`/`backtesting` (walk-forward
evaluation), and `signalfeed` (gate + weekly delivery + recap). Each story
below is written as a normal user story, with a note on what already
satisfies it and what (if anything) is still a gap.

## Epic: Prediction

**US-1 - Weekly forecast from Monday data**
As an operator, I want the system to predict a stock's Friday closing price
using only data available as of Monday, so I get an actionable read at the
start of the week and never on information that leaked from later in the
week.
- Acceptance: prediction is generated from a `weekday_anchored`
  `TradingModel` whose feature cut-off is Monday's session; no feature/label
  dated after the anchor is used.
- Status: done - `modeling/targets.py::weekday_anchored`,
  `modeling.dataset` point-in-time cut-offs, `research` providers' `as_of`
  discipline.

**US-2 - Direction + magnitude, not just up/down**
As an operator, I want to know not only whether a stock will go up or down,
but by roughly how much (%), so I can judge whether the move is worth
acting on.
- Acceptance: each weekly call includes `direction` (UP/DOWN/FLAT),
  `expected_return_pct`, `predicted_close`, and `reference_close`.
- Status: done - `signalfeed.models.WeeklySignal` + `services._interpret`.

**US-3 - Higher-accuracy model selection**
As an operator, I want to compare several candidate models/hyperparameters
and use whichever is most accurate for a given stock, rather than being
stuck with one hand-picked model.
- Acceptance: can sweep estimators x parameter grids over the same
  feature/target spec, rank by holdout accuracy, and promote the winner.
- Status: done - `modelsearch` app (`/model-search/`); trailing single
  holdout only, not walk-forward (see US-5 for the walk-forward check).

## Epic: Notification

**US-4 - Weekly push notification**
As an operator, I want to be notified (email/webhook/Telegram) at the start
of the week with the stock, predicted direction, and expected % move, so I
don't have to remember to check a dashboard.
- Acceptance: a Monday pre-open job sends one message per watched
  instrument that clears its accuracy gate; suppressed calls are visible in
  the UI but not pushed as noise.
- Status: done - `signalfeed.services.send_weekly_signals` +
  `delivery.deliver` (email/webhook/Telegram), `gate.evaluate_gate` for the
  suppression, `/signals/` action bar + `send_weekly_signals` command/task
  (task unscheduled - needs a cloud scheduler entry, see
  `AutomaticStockTrading/schedules.py`).

**US-5 - Only notify when the model has proven itself**
As an operator, I want to be notified only for stocks whose model has a
track record of adequate accuracy/skill/expected-move size, so I'm not
spammed with near-coin-flip calls.
- Acceptance: a `WatchItem` defines `min_directional_accuracy`/`min_skill`/
  `min_expected_move_pct`; a model that misses the bar produces a
  `suppressed` signal with a visible reason instead of a push.
- Status: done - `signalfeed.gate.evaluate_gate`, preferring live
  out-of-sample numbers from `modeling.leaderboard` and falling back to
  last-training holdout metrics.

**US-6 (optional/advisory) - Suggested position size**
As an operator, I want an advisory position-size suggestion (not an order)
alongside a deliverable UP/DOWN call, so I have a starting point for sizing
without the system trading on my behalf.
- Acceptance: `WatchItem` can opt in with `sizing_capital`; suggestion uses
  a half-Kelly-style edge from directional accuracy, capped at
  `max_position_pct`.
- Status: done - `signalfeed/sizing.py`; advisory only, no order is placed
  (PSX has no self-serve order API; live trading is a separate gated phase).

## Epic: Back-testing

**US-7 - Walk-forward back-test of the weekly approach**
As an operator, I want to back-test the Monday->Friday prediction approach
over historical data with retraining through time (not one static
train/test split), so the accuracy number I see reflects how the model
would have actually performed week over week.
- Acceptance: a `Backtest` can target a `weekday_anchored` model, march
  train/test windows forward with a `gap` embargo, and report directional
  accuracy, CAGR, max drawdown, Sharpe, and win rate translated from the
  forecast into a long/flat/short trading rule.
- Status: done - `backtesting` app (`/backtests/`), `weekday_anchored`
  scored at weekly decision cadence by `engine.py`. Also available on the
  leakage-strict path via `forecasting/backtesting/` +
  `ForecastBacktestRun` for the strict next-day predictors.

**US-8 - Detect an implausibly-good back-test (leakage check)**
As an operator, I want the system to flag a back-test whose skill looks too
good to be true, so I don't trust a result that's actually leaking future
information.
- Acceptance: a run with implausibly high walk-forward skill is flagged
  (`looks_leaky` / equivalent) rather than presented as a trustworthy
  number.
- Status: done (2026-09-12) - `backtesting`/`forecasting` leaky-skill
  flagging.

## Epic: Post-hoc accuracy checking

**US-9 - Grade each prediction once the real close arrives**
As an operator, I want each Friday's prediction automatically compared
against the actual close once the market data is in, so I can see whether
the model is holding up in live use, not just in a historical back-test.
- Acceptance: once Friday's `PriceBar` exists, `WeeklySignal.actual_close`/
  `actual_return_pct`/`was_correct` are backfilled without manual
  intervention.
- Status: done - `modeling.prediction.backfill_actuals` (also used
  generically by `modeling.ModelPrediction`), invoked by
  `signalfeed.services.recap_weekly_signals` and the
  `backfill_prediction_actuals` task; wired into the daily pipeline
  (`run_daily_pipeline`) for same-day predictions and the weekly recap for
  the Friday-anchored ones.

**US-10 - Weekly hit-rate recap**
As an operator, I want a Friday-afternoon summary of how many of this
week's calls were directionally correct, so I can track live accuracy over
time and decide whether to keep trusting a given model.
- Acceptance: a post-close job grades the week's signals and pushes a
  recap message (hit rate, count) through the same notification channels.
- Status: done - `signalfeed.services.recap_weekly_signals` +
  `recap_weekly_signals` command/task (task unscheduled - needs a cloud
  scheduler entry).
- Also surfaced continuously: `/signals/` shows trailing hit-rate, and the
  dashboard landing page shows a signal hit-rate KPI tile.

**US-11 - Model leaderboard over time**
As an operator, I want to see which active models are actually the most
accurate out-of-sample right now, so I can retire or replace an underperformer
before it damages the notification feed's credibility.
- Acceptance: a leaderboard ranks active `TradingModel`s by trailing
  out-of-sample accuracy/skill, degrading a bad row without breaking the
  page.
- Status: done - `modeling/leaderboard.py`, `/modeling/leaderboard/`.

## Gaps / follow-ups (not yet done)

- **US-12 - Scheduled, not just synchronous.** `send_weekly_signals_task`,
  `recap_weekly_signals_task`, and `train_weekly_models_task` exist but
  aren't wired to a cloud scheduler yet (`AutomaticStockTrading/schedules.py`
  only covers the daily chain + the three weekly triggers described in
  CLAUDE.md - confirm these are actually deployed/enabled in the target
  environment, since Phase 6/live-infra readiness is still open).
- **US-13 - Model-search over the walk-forward metric.** `modelsearch`
  ranks candidates on a single trailing holdout; there's no automated sweep
  that selects a model by walk-forward (`backtesting` app) accuracy instead.
  Worth a backlog item if holdout and walk-forward accuracy diverge in
  practice for a given symbol.

Related: `docs/SIGNALS_PLAN.md`, `docs/MODELING.md`, `docs/BACKTESTING.md`,
`docs/FORECASTING.md`.
