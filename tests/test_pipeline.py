"""
Test suite covering all three pipeline stages + secrets helper.

Run: pytest tests/ -v
"""
import os
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.ingestion.ingest import TransactionIngester, DataIngestionError
from src.transformation.transform import DataTransformer
from src.storage.store import DataStore
from src.monitoring.metrics import PipelineMetrics
from src.secrets import get_secret


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    """Write a minimal valid CSV to a temp directory."""
    rows = [
        {
            "transaction_id": f"txn-{i:04d}",
            "account_id": f"ACC100{i}",
            "timestamp": "2024-06-15T10:30:00",
            "merchant": "Amazon",
            "category": "retail",
            "amount": str(round(50.0 + i * 10, 2)),
            "currency": "GBP",
            "status": "completed",
            "country_code": "GB",
            "is_international": "False",
        }
        for i in range(10)
    ]
    import csv
    csv_file = tmp_path / "transactions.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return tmp_path


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    """Return a clean DataFrame for transformation tests."""
    data = {
        "transaction_id": [f"txn-{i}" for i in range(20)],
        "account_id":     [f"ACC{1000+i}" for i in range(20)],
        "timestamp":      ["2024-06-15T10:30:00"] * 20,
        "merchant":       ["Amazon", "Tesco", "", "Netflix"] * 5,
        "category":       ["retail", "groceries", "other", "streaming"] * 5,
        "amount":         [str(round(100.0 + i * 5, 2)) for i in range(20)],
        "currency":       ["GBP", "USD", "EUR", "GBP"] * 5,
        "status":         ["completed"] * 20,
        "country_code":   ["GB"] * 20,
        "is_international": ["False"] * 20,
    }
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# Ingestion tests
# ---------------------------------------------------------------------------

class TestIngestion:
    def test_ingest_valid_csv(self, sample_csv: Path):
        ingester = TransactionIngester(source_dir=str(sample_csv))
        df = ingester.ingest()
        assert len(df) == 10
        assert "transaction_id" in df.columns

    def test_ingest_empty_dir_raises(self, tmp_path: Path):
        with pytest.raises(DataIngestionError, match="No data files found"):
            TransactionIngester(str(tmp_path)).ingest()

    def test_ingest_missing_column_raises(self, tmp_path: Path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("col_a,col_b\n1,2\n")
        with pytest.raises(DataIngestionError, match="Schema validation failed"):
            TransactionIngester(str(tmp_path)).ingest()

    def test_metrics_updated(self, sample_csv: Path):
        metrics = PipelineMetrics()
        TransactionIngester(str(sample_csv), metrics=metrics).ingest()
        assert metrics.files_ingested.value == 1
        assert metrics.records_ingested.value == 10


# ---------------------------------------------------------------------------
# Transformation tests
# ---------------------------------------------------------------------------

class TestTransformation:
    def test_clean_fills_missing_merchant(self, sample_df: pd.DataFrame):
        transformer = DataTransformer()
        clean, _, _ = transformer.transform(sample_df)
        assert (clean["merchant"] == "").sum() == 0
        assert "UNKNOWN" in clean["merchant"].values or clean["merchant"].notna().all()

    def test_enrich_adds_gbp_amount(self, sample_df: pd.DataFrame):
        transformer = DataTransformer()
        clean, _, _ = transformer.transform(sample_df)
        assert "gbp_amount" in clean.columns
        assert clean["gbp_amount"].notna().all()

    def test_enrich_adds_risk_score(self, sample_df: pd.DataFrame):
        transformer = DataTransformer()
        clean, _, _ = transformer.transform(sample_df)
        assert "risk_score" in clean.columns
        assert clean["risk_score"].between(0, 3).all()

    def test_quarantine_negative_amounts(self):
        df = pd.DataFrame({
            "transaction_id": ["t1", "t2"],
            "account_id": ["A1", "A2"],
            "timestamp": ["2024-01-01T00:00:00"] * 2,
            "merchant": ["Amazon"] * 2,
            "category": ["retail"] * 2,
            "amount": ["-50", "100"],
            "currency": ["GBP"] * 2,
            "status": ["completed"] * 2,
            "country_code": ["GB"] * 2,
            "is_international": ["False"] * 2,
        })
        _, quarantine, _ = DataTransformer().transform(df)
        assert len(quarantine) == 1

    def test_aggregates_keys(self, sample_df: pd.DataFrame):
        _, _, aggs = DataTransformer().transform(sample_df)
        assert {"daily_spend", "category_breakdown", "high_risk_summary"} == set(aggs.keys())


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------

class TestStorage:
    def test_parquet_written(self, sample_df: pd.DataFrame, tmp_path: Path):
        clean, quarantine, aggs = DataTransformer().transform(sample_df)
        store = DataStore(output_dir=str(tmp_path))
        store.store(clean, quarantine, aggs)
        parquet_files = list((tmp_path / "transactions").rglob("*.parquet"))
        assert len(parquet_files) > 0

    def test_aggregate_parquet_written(self, sample_df: pd.DataFrame, tmp_path: Path):
        clean, quarantine, aggs = DataTransformer().transform(sample_df)
        DataStore(output_dir=str(tmp_path)).store(clean, quarantine, aggs)
        for name in ["daily_spend", "category_breakdown"]:
            assert (tmp_path / "aggregates" / f"{name}.parquet").exists()


# ---------------------------------------------------------------------------
# Secrets tests
# ---------------------------------------------------------------------------

class TestSecrets:
    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"MY_SECRET_KEY": "s3cr3t"}):
            get_secret.cache_clear()
            assert get_secret("MY_SECRET_KEY") == "s3cr3t"

    def test_missing_secret_returns_none(self):
        get_secret.cache_clear()
        result = get_secret("NONEXISTENT_KEY_XYZ123")
        assert result is None
