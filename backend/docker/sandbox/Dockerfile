FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    pandas==2.2.3 \
    numpy==1.26.4 \
    matplotlib==3.9.2 \
    plotly==5.24.1 \
    duckdb==1.1.2 \
    polars==1.12.0 \
    pyarrow==17.0.0 \
    sqlalchemy==2.0.35 \
    openpyxl==3.1.5 \
    pytest==8.3.3 \
    pytest-json-report==1.5.0

# Matplotlib should never try to open a display from inside the sandbox.
ENV MPLBACKEND=Agg
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY platform_sdk /opt/sdk/platform_sdk
ENV PYTHONPATH=/opt/sdk

WORKDIR /workspace
