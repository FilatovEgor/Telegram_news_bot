.PHONY: install test lint check run up down logs

install:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check .

check: lint test
	python -m compileall -q app migrations scripts

run:
	python -m app

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f bot
