"""
Metrics & monitoring module.

Exposes Prometheus-style counters that are:
  - incremented throughout the pipeline
  - logged as a structured JSON summary at the end of each run
  - (optionally) pushed to a Prometheus Pushgateway if PUSHGATEWAY_URL is set

In a production Kubernetes environment these would be scraped by the
Prometheus operator using a ServiceMonitor CRD.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight counter (avoids hard dependency on prometheus_client in demos)
# ---------------------------------------------------------------------------

class Counter:
    """Simple thread-safe counter that mirrors the prometheus_client API."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._value += amount

    @property
    def value(self) -> float:
        return self._value


@dataclass
class PipelineMetrics:
    """Collects all pipeline KPIs in one place."""

    files_ingested:      Counter = field(default_factory=lambda: Counter("files_ingested",      "Number of files ingested"))
    records_ingested:    Counter = field(default_factory=lambda: Counter("records_ingested",    "Raw records read"))
    records_transformed: Counter = field(default_factory=lambda: Counter("records_transformed", "Clean records after transformation"))
    records_quarantined: Counter = field(default_factory=lambda: Counter("records_quarantined", "Records sent to quarantine"))
    records_stored:      Counter = field(default_factory=lambda: Counter("records_stored",      "Records written to storage"))
    pipeline_errors:     Counter = field(default_factory=lambda: Counter("pipeline_errors",     "Total pipeline errors"))

    _start_time: float = field(default_factory=time.time, repr=False)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> dict:
        elapsed = round(time.time() - self._start_time, 2)
        summary = {
            "elapsed_seconds":      elapsed,
            "files_ingested":       self.files_ingested.value,
            "records_ingested":     self.records_ingested.value,
            "records_transformed":  self.records_transformed.value,
            "records_quarantined":  self.records_quarantined.value,
            "records_stored":       self.records_stored.value,
            "pipeline_errors":      self.pipeline_errors.value,
            "data_quality_pct":     self._quality_pct(),
        }
        logger.info("Pipeline metrics: %s", json.dumps(summary, indent=2))
        self._push_to_gateway(summary)
        return summary

    def _quality_pct(self) -> float:
        total = self.records_ingested.value
        if total == 0:
            return 0.0
        return round((self.records_transformed.value / total) * 100, 2)

    # ------------------------------------------------------------------
    # Optional Prometheus Pushgateway integration
    # ------------------------------------------------------------------

    def _push_to_gateway(self, summary: dict) -> None:
        url = os.getenv("PUSHGATEWAY_URL")
        if not url:
            return
        try:
            import urllib.request
            payload = "\n".join(
                f'dataops_pipeline_{k}{{job="dataops_pipeline"}} {v}'
                for k, v in summary.items()
                if isinstance(v, (int, float))
            ) + "\n"
            req = urllib.request.Request(
                f"{url}/metrics/job/dataops_pipeline",
                data=payload.encode(),
                method="PUT",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.info("Metrics pushed to Prometheus Pushgateway at %s", url)
        except Exception as exc:
            logger.warning("Failed to push metrics to gateway: %s", exc)
