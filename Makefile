# Yogii developer commands. Everything runs in SIMULATION mode.
PYTHON ?= python

.PHONY: install env up down logs migrate seed seed-reset train evaluate run-api run-web test test-backend test-backend-pg test-frontend check backup retention

install:            ## install backend (dev) and frontend dependencies
	$(PYTHON) -m pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

env:                ## write .env with random local secrets
	./scripts/generate-dev-env.sh

up:                 ## full stack on Docker (http://localhost:8080)
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	alembic upgrade head

seed:
	$(PYTHON) -m backend.scripts.seed

seed-reset:
	$(PYTHON) -m backend.scripts.seed --reset

train:
	$(PYTHON) -m backend.ml.train

evaluate:
	$(PYTHON) -m backend.ml.evaluate

run-api:
	uvicorn backend.main:app --reload --port 8000

run-web:
	cd frontend && npm run dev

test-backend:
	$(PYTHON) -m pytest backend/tests -q

test-backend-pg:    ## needs TEST_DATABASE_URL=postgresql://...
	$(PYTHON) -m pytest backend/tests -q

test-frontend:
	cd frontend && npm test && npm run typecheck

test: test-backend test-frontend

check: test         ## all checks, plus a production build of the web app
	cd frontend && npm run build

backup:
	$(PYTHON) -m backend.scripts.backup

retention:
	$(PYTHON) -m backend.scripts.retention
