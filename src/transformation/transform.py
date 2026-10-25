"""
Transformation module – cleans, enriches, and aggregates raw transaction data.

Cleaning rules applied:
  1. Parse and validate timestamps
  2. Cast numeric columns correctly
  3. Drop rows where transaction_id is null / duplicate
  4. Flag and quarantine negative amounts (anomalies)
  5. Fill missing merchant as "UNKNOWN"

Enrichment:
  - GBP-equivalent amount (using mock FX rates)
  - Risk score (rule-based: international + large amount + unusual category)
  - Date parts: year, month, day_of_week, hour

Aggregation:
  - Daily spend per account
  - Category breakdown
  - High-risk transaction summary
"""
import logging
from typing import Tuple

import pandas as pd

from src.monitoring.metrics import PipelineMetrics

logger = logging.getLogger(__name__)

# Mock FX rates to GBP
FX_RATES: dict[str, float] = {"GBP": 1.0, "USD": 0.79, "EUR": 0.86}

HIGH_RISK_CATEGORIES = {"transfer", "tax", "other"}
HIGH_RISK_THRESHOLD_GBP = 1_000.0


class DataTransformer:
    """
    Applies a multi-stage transformation to the raw ingested DataFrame.
    Returns (clean_df, quarantine_df, aggregates).
    """

    def __init__(self, metrics: PipelineMetrics | None = None):
        self.metrics = metrics or PipelineMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, raw: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
        df = raw.copy()
        df, quarantine = self._clean(df)
        df = self._enrich(df)
        aggregates = self._aggregate(df)
        logger.info(
            "Transform complete – %d clean, %d quarantined", len(df), len(quarantine)
        )
        self.metrics.records_transformed.inc(len(df))
        self.metrics.records_quarantined.inc(len(quarantine))
        return df, quarantine, aggregates

    # ------------------------------------------------------------------
    # Stage 1 – Clean
    # ------------------------------------------------------------------

    def _clean(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        issues = pd.Series([False] * len(df), index=df.index)

        # Parse timestamps
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        issues |= df["timestamp"].isna()

        # Cast amount
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        issues |= df["amount"].isna()

        # Flag negative amounts as anomalies
        issues |= df["amount"] < 0

        # Fill missing merchant
        df["merchant"] = df["merchant"].fillna("UNKNOWN").replace("", "UNKNOWN")

        # Deduplicate on transaction_id
        before = len(df)
        df = df.drop_duplicates(subset=["transaction_id"])
        dupes_removed = before - len(df)
        if dupes_removed:
            logger.warning("Removed %d duplicate transaction_id rows", dupes_removed)

        # Re-align issues index after dedup
        issues = issues.reindex(df.index, fill_value=False)

        quarantine = df[issues].copy()
        quarantine["quarantine_reason"] = "invalid_amount_or_timestamp"
        clean = df[~issues].copy()
        return clean, quarantine

    # ------------------------------------------------------------------
    # Stage 2 – Enrich
    # ------------------------------------------------------------------

    def _enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        # GBP-equivalent
        df["gbp_amount"] = df.apply(
            lambda r: round(r["amount"] * FX_RATES.get(str(r["currency"]), 1.0), 2),
            axis=1,
        )

        # Date parts
        df["year"]        = df["timestamp"].dt.year
        df["month"]       = df["timestamp"].dt.month
        df["day_of_week"] = df["timestamp"].dt.day_name()
        df["hour"]        = df["timestamp"].dt.hour

        # Rule-based risk score (0–3)
        df["risk_score"] = (
            df["is_international"].astype(str).str.lower().isin(["true", "1"]).astype(int)
            + (df["gbp_amount"] > HIGH_RISK_THRESHOLD_GBP).astype(int)
            + df["category"].isin(HIGH_RISK_CATEGORIES).astype(int)
        )
        df["is_high_risk"] = df["risk_score"] >= 2

        return df

    # ------------------------------------------------------------------
    # Stage 3 – Aggregate
    # ------------------------------------------------------------------

    def _aggregate(self, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
        # Daily spend per account
        daily_spend = (
            df.groupby(["account_id", df["timestamp"].dt.date])["gbp_amount"]
            .agg(total_spend="sum", txn_count="count")
            .reset_index()
            .rename(columns={"timestamp": "date"})
        )

        # Category breakdown (monthly)
        category_breakdown = (
            df.groupby(["year", "month", "category"])["gbp_amount"]
            .agg(total_spend="sum", txn_count="count")
            .reset_index()
        )

        # High-risk summary
        high_risk_summary = (
            df[df["is_high_risk"]]
            .groupby(["account_id", "category"])["gbp_amount"]
            .agg(total_risk_amount="sum", txn_count="count")
            .reset_index()
        )

        logger.info(
            "Aggregations produced: %d daily-spend rows, %d category rows, %d high-risk rows",
            len(daily_spend), len(category_breakdown), len(high_risk_summary),
        )
        return {
            "daily_spend": daily_spend,
            "category_breakdown": category_breakdown,
            "high_risk_summary": high_risk_summary,
        }
