# ProveKit — one-command dev workflow.
.PHONY: help setup backend frontend dev test lint build clean

# Pick the newest Python on PATH; the project needs 3.11+ (see .python-version). Using bare
# `python3` silently built a broken venv when that happened to be an old interpreter.
PYTHON := $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)

help:
	@echo "make setup     - create backend venv + install deps, install frontend deps"
	@echo "make backend   - run the API on :8000"
	@echo "make frontend  - run the web app on :3000"
	@echo "make test      - backend pytest + frontend typecheck"
	@echo "make lint      - ruff check on the backend"
	@echo "make build     - frontend production build"
	@echo "make clean     - remove venv, node_modules, local db"

setup:
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || { \
	  echo "✗ ProveKit needs Python 3.11+ (found '$(PYTHON)' = $$($(PYTHON) --version 2>&1))."; \
	  echo "  Install Python 3.13 (see .python-version), then re-run 'make setup'."; exit 1; }
	cd backend && $(PYTHON) -m venv venv && ./venv/bin/pip install -U pip && ./venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm install
	@echo "\n✓ Setup complete. Run 'make backend' and 'make frontend' in two terminals."

backend:
	cd backend && ./venv/bin/python -m uvicorn provekit.main:app --port 8000 --reload

frontend:
	cd frontend && npm run dev

test:
	cd backend && ./venv/bin/python -m pytest tests/ -q
	cd frontend && ./node_modules/.bin/tsc --noEmit

lint:
	cd backend && ./venv/bin/python -m ruff check provekit

build:
	cd frontend && npm run build

clean:
	rm -rf backend/venv backend/*.db backend/*.db-wal backend/*.db-shm backend/.provekit.key
	rm -rf frontend/node_modules frontend/.next
