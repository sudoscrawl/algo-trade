UV ?= uv

.DEFAULT_GOAL := help

.PHONY: help sync test migrate migration run lint format type

help:
	@printf '%s\n' \
		'Available targets:' \
		'  make sync                          Install locked dependencies' \
		'  make test                          Run the test suite' \
		'  make migrate                       Apply database migrations' \
		"  make migration message='summary'   Create a new migration" \
		'  make run                           Migrate, then start the bot' \
		'  make lint                          Run ruff linter' \
		'  make format                        Run ruff formatter' \
		'  make type                          Run ty type checker'

sync:
	$(UV) sync --all-groups --locked

test:
	$(UV) run --group dev pytest -q

migrate:
	$(UV) run alembic upgrade head

migration:
	@test -n "$(message)" || (echo "Usage: make migration message='describe the change'" >&2; exit 2)
	$(UV) run alembic revision --autogenerate -m "$(message)"

run: migrate
	$(UV) run python main.py

lint:
	$(UV) run --group dev ruff check . --fix

format:
	$(UV) run --group dev ruff format .

type:
	$(UV) run --group dev ty check .
