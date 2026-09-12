---
name: add-feature-provider
description: Add a new point-in-time feature provider (technical/news/fundamental/social/alt-data) to the research app so forecasting and modeling can consume it. Use when asked to add a new data source, indicator set, or feature signal.
---

# Add a research feature provider

`research` (see `docs/FORECASTING.md` and the project KB's
`psx-and-external-data.md` / `forecasting-layer.md`) supplies every feature
that `forecasting` and `modeling` train on, through one point-in-time
contract. Getting the point-in-time rule wrong silently leaks the future
into training — treat step 2 as non-negotiable.

## Steps

1. **New module under `research/providers/`** (mirror `technical.py` /
   `news.py` / `fundamentals.py` / `social.py`). If it wraps a third-party
   library (an API client, a scraper, a parsing lib), that import must live
   **only** in this module — nothing else may import the library directly
   (same rule as `marketdata/providers/psx.py` for `psxdata`). Catch the
   library's own exceptions and return an empty/`None` result rather than
   raising, so one bad source doesn't break a whole feature build.
2. **Implement `FeatureProvider`** (`research/providers/base.py`):
   `get_features(symbol, as_of, *, exchange) -> FeatureBundle`.
   - **Must not read anything dated after `as_of`.** If the underlying data
     has coarse timestamps (a whole trading day, a report filed on a date
     with no time), treat it as available only at the *next local midnight*
     — this repo's existing convention, not next open next bar (see
     `forecasting/features.py::assemble_training_frame`).
   - Return a `FeatureBundle`: a flat `features: dict[str, float]` (namespace
     keys like `news.sentiment_mean_7d`) plus human-readable `sources` for
     the citation trail. Never raise; return an empty bundle instead.
3. **Register**: `@register_feature_provider("key")` on the class
   (`research/providers/base.py`'s registry, mirrors
   `strategies/registry.py`). Import the new module from
   `research/apps.py::ready()` so the decorator actually fires — a provider
   only reliably shows up in the registry after Django app startup.
4. **Leak test — mandatory.** Add a test proving a fact/headline/report
   dated after `as_of` is excluded from the bundle (see
   `research/tests/` for the existing pattern per provider, e.g. the news
   leak test). This project's convention is: every provider ships with its
   own leak canary, not just a top-level one.
5. **Wire it into `services.build_feature_bundle()`** if it should be
   included by default, or leave it opt-in via the provider key list callers
   pass.
6. **If it should feed `modeling`**, add a `"research"` feature-spec entry
   referencing its keys (see `modeling/features.py`) — no code change needed
   there beyond using the new feature key string.
7. **Docs**: add it to the provider list in `docs/FORECASTING.md` and the
   KB's `psx-and-external-data.md` (or ask to update the KB — memory says
   this project's per-project KB should stay current).

## Verify

```
.venv/Scripts/python.exe -m pytest research modeling forecasting -q
```

Also run `python manage.py sync_research --symbol <SYMBOL>` locally to sanity
check the new provider doesn't blow up on the real `Instrument` data.
