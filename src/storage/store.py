"""
Storage module – persists clean data to Parquet and optionally to PostgreSQL.

Parquet output mirrors a data lake / S3 structure:
  output/
    transactions/year=2024/month=01/transactions.parquet
    aggregates/daily_spend.parquet
    aggregates/category_breakdown.parquet
    aggregates/high_risk_summary.parquet
    quarantine/quarantine_YYYYMMDDHHMMSS.parquet

PostgreSQL support is opt-in (set DATABASE_URL env var).
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

from src.monitoring.metrics import PipelineMetrics

logger = logging.getLogger(__name__)


class DataStore:
    """
    Writes clean, quarantine, and aggregate DataFrames to Parquet + (optional) PostgreSQL.
    """

    def __init__(
        self,
        output_dir: str = "output",
        metrics: Optional[PipelineMetrics] = None,
    ):
        self.output_dir = Path(output_dir)
        self.metrics = metrics or PipelineMetrics()
        self._engine = self._create_db_engine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        clean: pd.DataFrame,
        quarantine: pd.DataFrame,
        aggregates: dict[str, pd.DataFrame],
    ) -> None:
        self._write_partitioned_parquet(clean)
        self._write_quarantine(quarantine)
        self._write_aggregates(aggregates)
        if self._engine:
            self._write_to_postgres(clean, aggregates)
        logger.info("Storage complete.")
        self.metrics.records_stored.inc(len(clean))

    # ------------------------------------------------------------------
    # Parquet writers
    # ------------------------------------------------------------------

    def _write_partitioned_parquet(self, df: pd.DataFrame) -> None:
        """Write transactions partitioned by year/month (Hive-style)."""
        for (year, month), group in df.groupby(["year", "month"]):
            partition_path = (
                self.output_dir / "transactions" / f"year={year}" / f"month={month:02d}"
            )
            partition_path.mkdir(parents=True, exist_ok=True)
            out_file = partition_path / "transactions.parquet"
            group.drop(columns=["year", "month"]).to_parquet(out_file, index=False)
            logger.debug("Wrote %d rows to %s", len(group), out_file)

    def _write_quarantine(self, df: pd.DataFrame) -> None:
        if df.empty:
            logger.info("No quarantined records – skipping quarantine write.")
            return
        q_dir = self.output_dir / "quarantine"
        q_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        out_file = q_dir / f"quarantine_{ts}.parquet"
        df.to_parquet(out_file, index=False)
        logger.warning("Quarantined %d records → %s", len(df), out_file)

    def _write_aggregates(self, aggregates: dict[str, pd.DataFrame]) -> None:
        agg_dir = self.output_dir / "aggregates"
        agg_dir.mkdir(parents=True, exist_ok=True)
        for name, df in aggregates.items():
            out_file = agg_dir / f"{name}.parquet"
            df.to_parquet(out_file, index=False)
            logger.info("Aggregate '%s' → %s (%d rows)", name, out_file, len(df))

    # ------------------------------------------------------------------
    # PostgreSQL writer (optional)
    # ------------------------------------------------------------------

    def _create_db_engine(self):
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            return None
        try:
            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("PostgreSQL connection established.")
            return engine
        except Exception as exc:
            logger.warning("PostgreSQL unavailable, skipping: %s", exc)
            return None

    def _write_to_postgres(
        self, clean: pd.DataFrame, aggregates: dict[str, pd.DataFrame]
    ) -> None:
        """Upsert clean transactions and aggregates into PostgreSQL tables."""
        df_pg = clean.copy()
        df_pg["timestamp"] = df_pg["timestamp"].astype(str)
        df_pg.to_sql("transactions", self._engine, if_exists="replace", index=False, chunksize=500)
        logger.info("Wrote %d rows to PostgreSQL table 'transactions'", len(df_pg))

        for name, agg_df in aggregates.items():
            agg_pg = agg_df.copy()
            if "date" in agg_pg.columns:
                agg_pg["date"] = agg_pg["date"].astype(str)
            agg_pg.to_sql(name, self._engine, if_exists="replace", index=False)
            logger.info("Wrote %d rows to PostgreSQL table '%s'", len(agg_pg), name)
