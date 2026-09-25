FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install packages into a venv that any user can read
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Final runtime image
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 yogii

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy only the backend folder, not the whole repo
COPY --chown=yogii:yogii backend/ /app/backend/
COPY --chown=yogii:yogii alembic.ini /app/
COPY --chown=yogii:yogii database/ /app/database/
RUN chown yogii:yogii /app

USER yogii

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m backend.ml.train && python -m backend.scripts.seed && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]