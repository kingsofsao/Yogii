.PHONY: up down build migrate seed train-model test logs reset-demo run-local

# Docker commands
up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

# Local backend / ML commands
migrate:
	alembic upgrade head

seed:
	python -m backend.scripts.seed

train-model:
	python -m backend.ml.train

test:
	pytest backend/tests -v

reset-demo:
	python -m backend.scripts.seed

run-api:
	uvicorn backend.main:app --reload --port 8000

run-web:
	cd frontend && npm run dev
