# Yogii API image. Runs as a non-root user. Migrations and seeding run as
# separate one-shot services (see docker-compose.yml), not at API start-up.
FROM python:3.11-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM python:3.11-slim
# No extra OS packages: XGBoost wheels bundle their OpenMP runtime. Database
# backups use pg_dump from the Postgres container (see docs/DEPLOYMENT.md).
RUN useradd --create-home --uid 10001 yogii
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --chown=yogii:yogii alembic.ini /app/
COPY --chown=yogii:yogii database/ /app/database/
COPY --chown=yogii:yogii backend/ /app/backend/
USER yogii
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=2)"
# --proxy-headers trusts X-Forwarded-For from the web proxy. The API port is only
# reachable on the internal Compose network, never published to the host.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
