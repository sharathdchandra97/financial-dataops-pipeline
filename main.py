"""
Pipeline entry point – orchestrates Ingest → Transform → Store.

Usage:
    python main.py --source data/ --output output/
    python main.py --source data/ --output output/ --log-level DEBUG
"""
import argparse
import json
import logging
import os
import sys

from src.ingestion.ingest import TransactionIngester, DataIngestionError
from src.transformation.transform import DataTransformer
from src.storage.store import DataStore
from src.monitoring.metrics import PipelineMetrics
from src.secrets import get_secret


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pipeline.log", mode="a", encoding="utf-8"),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial DataOps Pipeline")
    parser.add_argument("--source",    default="data",   help="Source directory for input files")
    parser.add_argument("--output",    default="output", help="Output directory for Parquet files")
    parser.add_argument("--log-level", default="INFO",   help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)
    logger = logging.getLogger("pipeline.main")

    # Resolve secrets (DATABASE_URL may come from Vault or env)
    db_url = get_secret("DATABASE_URL", vault_path="dataops/prod")
    if db_url:
        os.environ["DATABASE_URL"] = db_url  # make available to DataStore

    metrics = PipelineMetrics()

    try:
        # --- INGEST ---
        logger.info("=" * 60)
        logger.info("Stage 1/3 – INGEST")
        ingester = TransactionIngester(source_dir=args.source, metrics=metrics)
        raw_df = ingester.ingest()

        # --- TRANSFORM ---
        logger.info("=" * 60)
        logger.info("Stage 2/3 – TRANSFORM")
        transformer = DataTransformer(metrics=metrics)
        clean_df, quarantine_df, aggregates = transformer.transform(raw_df)

        # --- STORE ---
        logger.info("=" * 60)
        logger.info("Stage 3/3 – STORE")
        store = DataStore(output_dir=args.output, metrics=metrics)
        store.store(clean_df, quarantine_df, aggregates)

    except DataIngestionError as exc:
        metrics.pipeline_errors.inc()
        logger.error("Ingestion failed: %s", exc)
        metrics.report()
        return 1
    except Exception as exc:
        metrics.pipeline_errors.inc()
        logger.exception("Unexpected pipeline error: %s", exc)
        metrics.report()
        return 1
    else:
        summary = metrics.report()
        logger.info("=" * 60)
        logger.info("Pipeline completed successfully.")
        logger.info("Summary:\n%s", json.dumps(summary, indent=2))
        return 0


if __name__ == "__main__":
    sys.exit(main())
