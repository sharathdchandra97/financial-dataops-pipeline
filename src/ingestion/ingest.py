"""
Ingestion module – loads financial transaction data from a local directory
(simulating an S3 bucket drop-zone) and validates schema on arrival.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd

from src.monitoring.metrics import PipelineMetrics

logger = logging.getLogger(__name__)


EXPECTED_COLUMNS = {
    "transaction_id", "account_id", "timestamp",
    "merchant", "category", "amount", "currency",
    "status", "country_code", "is_international",
}


class DataIngestionError(Exception):
    """Raised when ingestion fails validation."""


class TransactionIngester:
    """
    Reads CSV / JSON files from a source directory and returns a raw DataFrame.

    In production this would be replaced by an S3-triggered Lambda / Airflow
    sensor, but the interface stays identical (returns pd.DataFrame).
    """

    def __init__(self, source_dir: str, metrics: Optional[PipelineMetrics] = None):
        self.source_dir = Path(source_dir)
        self.metrics = metrics or PipelineMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self) -> pd.DataFrame:
        """Read all supported files from source_dir and return combined df."""
        files = self._discover_files()
        if not files:
            raise DataIngestionError(f"No data files found in {self.source_dir}")

        frames = []
        for fp in files:
            logger.info("Ingesting %s", fp.name)
            df = self._read_file(fp)
            self._validate_schema(df, fp)
            frames.append(df)
            self.metrics.files_ingested.inc()
            self.metrics.records_ingested.inc(len(df))

        combined = pd.concat(frames, ignore_index=True)
        logger.info("Ingestion complete – %d records from %d file(s)", len(combined), len(files))
        return combined

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _discover_files(self) -> list[Path]:
        return sorted(
            fp for fp in self.source_dir.iterdir()
            if fp.suffix in {".csv", ".json"} and fp.is_file()
        )

    def _read_file(self, fp: Path) -> pd.DataFrame:
        try:
            if fp.suffix == ".csv":
                return pd.read_csv(fp, dtype=str)         # read as str; cast later
            else:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
                return pd.DataFrame(data if isinstance(data, list) else [data])
        except Exception as exc:
            raise DataIngestionError(f"Failed to read {fp}: {exc}") from exc

    def _validate_schema(self, df: pd.DataFrame, fp: Path) -> None:
        missing = EXPECTED_COLUMNS - set(df.columns)
        if missing:
            raise DataIngestionError(
                f"Schema validation failed for {fp.name}: missing columns {missing}"
            )
        logger.debug("Schema OK for %s", fp.name)
