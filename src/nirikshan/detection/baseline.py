"""Dynamic per-(service, metric) baselines.

We keep a running summary rather than re-scanning history on every evaluation:

* ``mean`` / ``std``     - Welford-style batch update over recent samples
* ``ewma`` / ``ewvar``   - exponentially weighted mean & variance (adapts fast)
* ``p50`` / ``p95``      - robust percentiles from the recent window

The EWMA half-life is deliberately long-ish so that a genuine incident (a step
change lasting minutes) is flagged instead of being absorbed into the baseline,
while ordinary diurnal drift is tracked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.models import MetricBaseline, Service, TelemetryMetric

EWMA_ALPHA = 0.15
MIN_SAMPLES = 8


@dataclass
class BaselineView:
    mean: float
    std: float
    ewma: float
    ewvar: float
    p50: float
    p95: float
    sample_count: int

    @property
    def ewstd(self) -> float:
        return math.sqrt(max(self.ewvar, 0.0))

    def band(self, sigma: float = 3.0) -> tuple[float, float]:
        spread = max(self.std, self.ewstd, 1e-9)
        return self.mean - sigma * spread, self.mean + sigma * spread


def _percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if values.size else 0.0


def recompute_baseline(
    db: Session,
    service: Service,
    metric_name: str,
    *,
    lookback_minutes: int = 240,
    exclude_last_minutes: int = 25,
) -> BaselineView | None:
    """Rebuild a baseline from recent history, excluding the most recent minutes
    (so an in-progress anomaly does not poison the reference distribution)."""
    until = utcnow() - timedelta(minutes=exclude_last_minutes)
    since = until - timedelta(minutes=lookback_minutes)
    rows = list(
        db.scalars(
            select(TelemetryMetric.value).where(
                TelemetryMetric.service_id == service.id,
                TelemetryMetric.metric_name == metric_name,
                TelemetryMetric.ts >= since,
                TelemetryMetric.ts <= until,
            )
        )
    )
    if len(rows) < MIN_SAMPLES:
        return None

    arr = np.asarray(rows, dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=1)) if arr.size > 1 else 0.0

    # EWMA / EWVAR walk in time order
    ewma = float(arr[0])
    ewvar = 0.0
    for x in arr[1:]:
        diff = x - ewma
        ewma += EWMA_ALPHA * diff
        ewvar = (1 - EWMA_ALPHA) * (ewvar + EWMA_ALPHA * diff * diff)

    view = BaselineView(
        mean=mean,
        std=std,
        ewma=ewma,
        ewvar=ewvar,
        p50=_percentile(arr, 50),
        p95=_percentile(arr, 95),
        sample_count=int(arr.size),
    )
    _persist(db, service, metric_name, view, since)
    return view


def _persist(db: Session, service: Service, metric_name: str, view: BaselineView, since) -> None:
    row = db.scalar(
        select(MetricBaseline).where(
            MetricBaseline.service_id == service.id,
            MetricBaseline.metric_name == metric_name,
        )
    )
    if row is None:
        row = MetricBaseline(
            environment_id=service.environment_id,
            service_id=service.id,
            metric_name=metric_name,
        )
        db.add(row)
    row.mean = view.mean
    row.std = view.std
    row.ewma = view.ewma
    row.ewvar = view.ewvar
    row.p50 = view.p50
    row.p95 = view.p95
    row.sample_count = view.sample_count
    row.updated_from_ts = since
    db.flush()


def load_baseline(db: Session, service_id: str, metric_name: str) -> BaselineView | None:
    row = db.scalar(
        select(MetricBaseline).where(
            MetricBaseline.service_id == service_id,
            MetricBaseline.metric_name == metric_name,
        )
    )
    if row is None or row.sample_count < MIN_SAMPLES:
        return None
    return BaselineView(
        mean=row.mean,
        std=row.std,
        ewma=row.ewma,
        ewvar=row.ewvar,
        p50=row.p50,
        p95=row.p95,
        sample_count=row.sample_count,
    )
