"""Company-fundamentals features.

STUB. The `FeatureProvider` interface and the point-in-time query are real
and correct; what's missing is a live data source. PSX filings aren't
available through a free API, so for now `CompanyFundamental` rows are
loaded manually or from CSV (see `load_fundamentals_csv`). Until rows
exist, this provider returns an empty bundle - it never blocks assembly.

Features (from the latest report with ``as_of_report_date < as_of.date()``):
one ``fundamentals.<ratio>`` per key in the stored ``ratios`` JSON, plus
``fundamentals.report_age_days``.

Only a publication date is stored, not a release time. Conservatively
make reports available the following day to avoid intraday look-ahead.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime

from ..models import CompanyFundamental
from .base import FeatureBundle, FeatureProvider, register_feature_provider

logger = logging.getLogger(__name__)

NAMESPACE = "fundamentals"


def load_fundamentals_csv(path: str, exchange: str = "PSX") -> int:
    """Load rows from a CSV with columns: symbol, as_of_report_date
    (YYYY-MM-DD), then one column per ratio. Returns rows upserted."""
    count = 0
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = row.pop("symbol").strip()
            report_date = date.fromisoformat(row.pop("as_of_report_date").strip())
            ratios = {k: float(v) for k, v in row.items() if v not in (None, "")}
            CompanyFundamental.objects.update_or_create(
                exchange=exchange,
                symbol=symbol,
                as_of_report_date=report_date,
                defaults={"ratios": ratios, "source": f"csv:{path}"},
            )
            count += 1
    return count


def fundamentals_features(
    symbol: str, as_of: datetime, *, exchange: str = "PSX"
) -> dict[str, float]:
    report = (
        CompanyFundamental.objects.filter(
            exchange=exchange, symbol=symbol, as_of_report_date__lt=as_of.date()
        )
        .order_by("-as_of_report_date")
        .first()
    )
    if report is None:
        return {}

    out = {
        f"{NAMESPACE}.{k}": float(v)
        for k, v in report.ratios.items()
        if isinstance(v, (int, float))
    }
    out[f"{NAMESPACE}.report_age_days"] = float((as_of.date() - report.as_of_report_date).days)
    return out


@register_feature_provider("fundamentals")
class FundamentalsProvider(FeatureProvider):
    namespace = NAMESPACE
    display_name = "Company Fundamentals (stub - manual/CSV load)"

    def get_features(self, symbol: str, as_of: datetime, *, exchange: str = "PSX") -> FeatureBundle:
        features = fundamentals_features(symbol, as_of, exchange=exchange)
        return FeatureBundle(
            symbol=symbol,
            as_of=as_of,
            exchange=exchange,
            features=features,
            sources=["CompanyFundamental rows (manual/CSV load)"],
        )
