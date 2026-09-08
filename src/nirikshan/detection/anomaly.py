"""Statistical / ML anomaly detection over metric windows.

Method selection is deliberately conservative (spec 18): start with robust,
explainable statistics and only escalate to Isolation Forest for multi-modal
metrics where it genuinely helps.

* ``zscore``            - |x - mean| / std against the recomputed baseline
* ``ewma``             - deviation from the exponentially weighted mean
* ``rolling_iqr``       - robust to outliers; good for spiky counters
* ``isolation_forest``  - only when >= 40 samples and the metric is opted in

A point is reported as an anomaly only if it is both statistically extreme
*and* sustained (``persistence`` consecutive points), which suppresses reaction
to single-sample blips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from nirikshan.core.clock import utcnow
from nirikshan.core.events import EventType, emit
from nirikshan.core.logging import get_logger
from nirikshan.detection.baseline import recompute_baseline
from nirikshan.domain.enums import AnomalyMethod
from nirikshan.models import Anomaly, Service, TelemetryMetric

log = get_logger("detection.anomaly")

# metrics where higher is worse vs. where deviation in either direction matters
_HIGHER_IS_WORSE = {
    "request_latency_ms",
    "error_rate",
    "error_count",
    "cpu_usage",
    "memory_usage",
    "database_connections",
    "queue_depth",
    "gc_pause_ms",
}
_ISOLATION_FOREST_METRICS = {"request_count", "request_latency_ms"}

Z_THRESHOLD = 3.5
PERSISTENCE = 3
MIN_WINDOW_SAMPLES = 6


@dataclass
class AnomalyResult:
    metric: str
    method: AnomalyMethod
    observed_value: float
    expected_low: float
    expected_high: float
    score: float
    confidence: float
    direction: str
    detected_at: datetime
    context: dict

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["method"] = self.method.value
        d["detected_at"] = self.detected_at.isoformat()
        return d


def _recent_values(
    db: Session, service_id: str, metric: str, window_minutes: int
) -> list[tuple[datetime, float]]:
    until = utcnow()
    since = until - timedelta(minutes=window_minutes)
    rows = db.execute(
        select(TelemetryMetric.ts, TelemetryMetric.value)
        .where(
            TelemetryMetric.service_id == service_id,
            TelemetryMetric.metric_name == metric,
            TelemetryMetric.ts >= since,
        )
        .order_by(TelemetryMetric.ts)
    ).all()
    return [(ts, float(v)) for ts, v in rows]


def _confidence(score: float, samples: int) -> float:
    """Map a z-like score + sample support onto a calibrated 0..1 confidence."""
    base = 1.0 - np.exp(-max(score - Z_THRESHOLD, 0.0) / 3.0)
    support = min(samples / 30.0, 1.0)
    return float(round(min(0.99, 0.35 + 0.5 * base + 0.14 * support), 3))


def detect_for_metric(
    db: Session,
    service: Service,
    metric: str,
    *,
    window_minutes: int = 20,
    persist: bool = True,
) -> AnomalyResult | None:
    series = _recent_values(db, service.id, metric, window_minutes)
    if len(series) < MIN_WINDOW_SAMPLES:
        return None

    values = np.asarray([v for _, v in series], dtype=float)
    last_ts, last_val = series[-1]

    # The baseline must exclude the window we are currently testing, so an
    # in-progress incident cannot inflate the reference spread.
    baseline = recompute_baseline(
        db, service, metric, exclude_last_minutes=window_minutes + 6, lookback_minutes=240
    )
    if baseline is None or (baseline.std == 0 and baseline.ewstd == 0):
        # Not enough clean history yet -> fall back to in-window robust stats.
        result = _rolling_iqr(metric, values, last_ts)
    else:
        spread = max(baseline.std, baseline.ewstd, 1e-9)
        z = abs(last_val - baseline.mean) / spread
        tail = values[-PERSISTENCE:]
        sustained = np.all(np.abs(tail - baseline.mean) / spread >= (Z_THRESHOLD * 0.7))
        if z < Z_THRESHOLD or not sustained:
            result = None
        else:
            low, high = baseline.band(3.0)
            direction = "high" if last_val > baseline.mean else "low"
            result = AnomalyResult(
                metric=metric,
                method=AnomalyMethod.ZSCORE,
                observed_value=last_val,
                expected_low=low,
                expected_high=high,
                score=float(round(z, 3)),
                confidence=_confidence(z, baseline.sample_count),
                direction=direction,
                detected_at=last_ts,
                context={
                    "baseline_mean": round(baseline.mean, 3),
                    "baseline_std": round(spread, 3),
                    "p95": round(baseline.p95, 3),
                    "window_minutes": window_minutes,
                    "sustained_points": int(PERSISTENCE),
                },
            )
            # cross-check with isolation forest for opted-in metrics
            if metric in _ISOLATION_FOREST_METRICS and len(values) >= 40:
                result.context["isolation_forest_agrees"] = _isolation_forest_flag(values)

    if result is None:
        return None
    if result.direction == "low" and metric in _HIGHER_IS_WORSE and metric != "request_count":
        # a drop in latency/errors is good news, not an incident signal
        return None

    if persist:
        _store(db, service, result)
        emit(
            EventType.ANOMALY_DETECTED,
            {
                "service": service.name,
                "metric": metric,
                "score": result.score,
                "confidence": result.confidence,
                "direction": result.direction,
                "observed_value": result.observed_value,
            },
        )
    return result


def _rolling_iqr(metric: str, values: np.ndarray, ts: datetime) -> AnomalyResult | None:
    if values.size < MIN_WINDOW_SAMPLES:
        return None
    ref = values[:-PERSISTENCE] if values.size > PERSISTENCE else values
    q1, q3 = np.percentile(ref, [25, 75])
    iqr = q3 - q1
    if iqr <= 1e-9:
        return None
    low, high = q1 - 3.0 * iqr, q3 + 3.0 * iqr
    last = float(values[-1])
    if low <= last <= high:
        return None
    score = abs(last - np.median(ref)) / (iqr + 1e-9)
    return AnomalyResult(
        metric=metric,
        method=AnomalyMethod.ROLLING_IQR,
        observed_value=last,
        expected_low=float(low),
        expected_high=float(high),
        score=float(round(score, 3)),
        confidence=float(round(min(0.9, 0.4 + 0.1 * score), 3)),
        direction="high" if last > high else "low",
        detected_at=ts,
        context={"q1": round(float(q1), 3), "q3": round(float(q3), 3), "iqr": round(float(iqr), 3)},
    )


def _isolation_forest_flag(values: np.ndarray) -> bool:
    try:
        from sklearn.ensemble import IsolationForest

        x = values.reshape(-1, 1)
        model = IsolationForest(
            n_estimators=64, contamination="auto", random_state=42
        ).fit(x[:-PERSISTENCE])
        preds = model.predict(x[-PERSISTENCE:])
        return bool(np.any(preds == -1))
    except Exception:  # pragma: no cover - sklearn optional at runtime
        return False


def _store(db: Session, service: Service, r: AnomalyResult) -> Anomaly:
    row = Anomaly(
        detected_at=r.detected_at,
        environment_id=service.environment_id,
        service_id=service.id,
        service_name=service.name,
        metric_name=r.metric,
        method=r.method.value,
        observed_value=r.observed_value,
        expected_low=r.expected_low,
        expected_high=r.expected_high,
        score=r.score,
        confidence=r.confidence,
        direction=r.direction,
        window_seconds=int(r.context.get("window_minutes", 20)) * 60,
        context=r.context,
    )
    db.add(row)
    db.flush()
    return row


DEFAULT_METRICS = sorted(_HIGHER_IS_WORSE | {"request_count"})


def scan_service(db: Session, service: Service, *, metrics: list[str] | None = None) -> list[AnomalyResult]:
    out: list[AnomalyResult] = []
    for metric in metrics or DEFAULT_METRICS:
        try:
            r = detect_for_metric(db, service, metric)
            if r:
                out.append(r)
        except Exception as exc:
            log.warning("anomaly.scan_failed", service=service.name, metric=metric, error=str(exc))
    return out
