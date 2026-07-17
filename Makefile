# AgentMan — one-command dev workflow.
.PHONY: help setup backend frontend dev test lint build clean

help:
	@echo "make setup     - create backend venv + install deps, install frontend deps"
	@echo "make backend   - run the API on :8100"
	@echo "make frontend  - run the web app on :3001"
	@echo "make test      - backend pytest + frontend typecheck"
	@echo "make lint      - ruff check on the backend"
	@echo "make build     - frontend production build"
	@echo "make clean     - remove venv, node_modules, local db"

setup:
	cd backend && python3 -m venv venv && ./venv/bin/pip install -U pip && ./venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install
	@echo "\n✓ Setup complete. Run 'make backend' and 'make frontend' in two terminals."

backend:
	cd backend && ./venv/bin/python -m uvicorn agentman.main:app --port 8100 --reload

frontend:
	cd frontend && npm run dev

test:
	cd backend && ./venv/bin/python -m pytest tests/ -q
	cd frontend && ./node_modules/.bin/tsc --noEmit

lint:
	cd backend && ./venv/bin/python -m ruff check agentman

build:
	cd frontend && npm run build

clean:
	rm -rf backend/venv backend/*.db backend/*.db-wal backend/*.db-shm backend/.agentman.key
	rm -rf frontend/node_modules frontend/.next
