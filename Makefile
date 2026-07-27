.PHONY: up dev down logs test lint smoke ps

up:
	docker compose up -d --build

dev:
	docker compose -f compose.yaml -f compose.dev.yaml up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200 api worker

ps:
	docker compose ps

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check app tests scripts

smoke:
	python3 scripts/smoke.py
