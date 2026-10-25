FROM python:3.11-slim AS base

# Security: run as non-root
RUN groupadd -r pipeline && useradd -r -g pipeline pipeline

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# --- Dependencies layer (cached separately) ---
FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Final image ---
FROM deps AS final
COPY --chown=pipeline:pipeline src/    ./src/
COPY --chown=pipeline:pipeline main.py .
COPY --chown=pipeline:pipeline data/   ./data/

# Switch to non-root user
USER pipeline

# Health check: verify Python env is sane
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import pandas, pyarrow; print('OK')"

ENTRYPOINT ["python", "main.py"]
CMD ["--source", "data", "--output", "output"]

LABEL org.opencontainers.image.title="Financial DataOps Pipeline"
LABEL org.opencontainers.image.description="Ingest, transform, and store financial transaction data"
LABEL org.opencontainers.image.source="https://github.com/YOUR_ORG/financial-dataops-pipeline"
