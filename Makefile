.PHONY: build-sandbox up down migrate test seed-demo

build-sandbox:
	docker build -t mini-foundry-sandbox:0.5 backend/docker/sandbox

up:
	docker compose up -d

down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

test:
	cd backend && pytest -q

seed-demo:
	cd backend && python -m app.seeds.demo --force
