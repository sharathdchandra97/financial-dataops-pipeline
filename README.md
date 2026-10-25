# Financial DataOps Pipeline

> **DataOps pipeline for financial transaction data** — ingests, transforms, and stores transaction records for downstream analytics and ML use cases.

[![CI/CD](https://github.com/sharathdchandra97/financial-dataops-pipeline/actions/workflows/pipeline.yml/badge.svg)](https://github.com/sharathdchandra97/financial-dataops-pipeline/actions)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                     GitHub Actions CI/CD                         │
│  lint → security scan → tests → docker build → terraform → run  │
└───────────────────────────────┬──────────────────────────────────┘
                                │
         ┌──────────────────────▼──────────────────────┐
         │           DataOps Pipeline (ECS Fargate)     │
         │                                              │
         │  ┌─────────┐   ┌───────────┐  ┌──────────┐  │
         │  │  INGEST  │──▶│ TRANSFORM │─▶│  STORE   │  │
         │  │ CSV/JSON │   │ Clean     │  │ Parquet  │  │
         │  │ (S3/dir) │   │ Enrich    │  │ PostgreSQL│ │
         │  │          │   │ Aggregate │  │ (Redshift)│ │
         │  └─────────┘   └───────────┘  └──────────┘  │
         └──────────┬───────────────────────────────────┘
                    │
    ┌───────────────▼──────────────────┐
    │  Observability Stack              │
    │  Prometheus → Grafana             │
    │  CloudWatch Logs + Alarms         │
    │  SNS Alerts                       │
    └───────────────────────────────────┘
```

## Quick Start (Local)

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- Terraform ≥ 1.8 (optional, for cloud provisioning)

### 1. Clone & install

```bash
git clone https://github.com/sharathdchandra97/financial-dataops-pipeline
cd financial-dataops-pipeline
pip install -r requirements.txt
```

### 2. Generate sample data

```bash
cd data && python generate_sample_data.py && cd ..
```

### 3. Run the pipeline locally

```bash
# Without database (Parquet output only)
python main.py --source data --output output --log-level INFO

# With full observability stack
docker-compose up -d          # starts Postgres, Vault, Prometheus, Grafana
docker-compose run pipeline   # runs the pipeline
```

### 4. Run tests

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

### 5. View dashboards

| Service    | URL                    | Credentials         |
|------------|------------------------|---------------------|
| Grafana    | http://localhost:3000  | admin / admin       |
| Prometheus | http://localhost:9090  | —                   |
| Pushgateway| http://localhost:9091  | —                   |
| Vault UI   | http://localhost:8200  | Token: root         |

---

## Project Structure

```
financial-dataops-pipeline/
├── .github/workflows/
│   └── pipeline.yml          # 6-stage CI/CD workflow
├── data/
│   └── generate_sample_data.py
├── docker/
│   ├── Dockerfile
│   └── prometheus.yml
├── src/
│   ├── ingestion/ingest.py   # Stage 1: load & schema validate
│   ├── transformation/
│   │   └── transform.py      # Stage 2: clean, enrich, aggregate
│   ├── storage/store.py      # Stage 3: Parquet + PostgreSQL
│   ├── monitoring/metrics.py # Prometheus counters + reporting
│   └── secrets.py            # Vault / env fallback
├── terraform/
│   ├── main.tf               # S3, ECS Fargate, CloudWatch, IAM
│   ├── variables.tf
│   └── outputs.tf
├── tests/
│   └── test_pipeline.py      # ~15 unit + integration tests
├── docker-compose.yml
├── main.py                   # Pipeline orchestrator
└── requirements.txt
```

---

## Pipeline Stages

### Stage 1 — Ingest
- Discovers CSV/JSON files from source directory (simulated S3 drop-zone)
- Validates schema against required column set
- Tracks `files_ingested` and `records_ingested` metrics

### Stage 2 — Transform
**Clean:**
- Parse timestamps; quarantine invalid rows
- Cast `amount` to float; quarantine negatives
- Fill blank merchants with `UNKNOWN`
- De-duplicate on `transaction_id`

**Enrich:**
- Convert all amounts to GBP equivalent (mock FX rates)
- Extract date parts (year, month, day_of_week, hour)
- Compute rule-based `risk_score` (0–3)

**Aggregate:**
- Daily spend per account
- Monthly category breakdown
- High-risk transaction summary

### Stage 3 — Store
- Hive-partitioned Parquet (`year=YYYY/month=MM/`) — data lake structure
- Separate quarantine Parquet with timestamp-based naming
- Optional PostgreSQL write via SQLAlchemy (mock Redshift)

---

## Secrets Management

Priority order:
1. **HashiCorp Vault KV v2** — `VAULT_ADDR` + `VAULT_TOKEN` env vars
2. **Environment variables** — fallback for local dev / CI

```python
from src.secrets import get_secret
db_url = get_secret("DATABASE_URL", vault_path="dataops/prod")
```

---

## Infrastructure (Terraform)

Provisions on AWS (eu-west-2):
- **S3** — data lake with KMS encryption, versioning, intelligent-tiering lifecycle
- **ECR** — container registry with image scanning enabled
- **ECS Fargate** — serverless task execution (no EC2 to manage)
- **CloudWatch** — log group + metric alarm (pipeline errors → SNS)
- **SSM Parameter Store** — SecureString parameters for DATABASE_URL and VAULT_TOKEN

---

## Monitoring & Observability

| Signal | Tool | Where |
|--------|------|--------|
| Pipeline metrics | Prometheus Pushgateway | `PUSHGATEWAY_URL` |
| Dashboards | Grafana | localhost:3000 |
| Container logs | CloudWatch Logs | `/ecs/financial-dataops-pipeline` |
| Error alerts | SNS → Email / Slack | On `pipeline_errors > 0` |
| Data quality % | Structured JSON log | `pipeline.log` |

---

## CI/CD (GitHub Actions)

6 sequential jobs on `push` to `main`:
1. **Lint** — ruff + mypy
2. **Security** — Trivy (CRITICAL/HIGH CVEs) + detect-secrets
3. **Test** — pytest matrix (Python 3.10/3.11/3.12) with Postgres service
4. **Build** — Docker image → GHCR
5. **Terraform** — plan + apply to AWS
6. **Deploy** — pull image, sync S3 data, run container, sync output back to S3

---

## Data Quality Approach

- **Schema validation** at ingestion boundary
- **Quarantine pattern** — bad rows isolated, never silently dropped
- **Deduplication** on `transaction_id`
- **Metrics** — data quality % (`records_transformed / records_ingested × 100`)
- **Test coverage** — negative amounts, missing merchants, empty directories, schema violations all tested

---

## Compliance & Security

- Non-root Docker container
- Secrets never hardcoded — Vault KV v2 or environment variables only
- S3 KMS encryption at rest
- RBAC via IAM roles (least-privilege)
- Trivy image scanning in CI
- FCA-relevant audit trail via structured logging
