FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final runtime image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed wheels/packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app

# Create unprivileged application user
RUN useradd -m -u 1000 yogii && chown -R yogii:yogii /app

COPY --chown=yogii:yogii . /app/backend/
COPY --chown=yogii:yogii alembic.ini /app/
COPY --chown=yogii:yogii database/ /app/database/

USER yogii

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m backend.ml.train && python -m backend.scripts.seed && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
