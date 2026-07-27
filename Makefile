.PHONY: up down logs test lint smoke graph ps

up:
	docker compose up -d --build

graph:
	docker compose --profile graph up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200 api worker

ps:
	docker compose ps

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check app tests

smoke:
	python3 scripts/smoke.py

