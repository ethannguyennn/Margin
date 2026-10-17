# Margin -- team build contract. Works with GNU make on Linux/macOS and
# mingw32-make / GNU make on Windows (no shell-specific syntax in recipes).
#
#   make install     # one-time: venv deps for the relay (+ dev/test tools)
#   make dev-relay   # uvicorn, reload, MOCK_MODE from .env, bound to 0.0.0.0 for LAN sideload
#   make dev-app     # cd app && npm run dev
#   make sim         # even simulator against the dev app
#   make test        # pytest relay/tests + npm test in app (must stay green)
#   make seed        # python db/seed.py            (Part 5)
#   make eval        # python eval/run_eval.py      (Part 5)
#   make latency     # p50/p95 per stage from the events hypertable
#   make deploy      # docker compose up -d --build (run on the Vultr VM)

PORT ?= 8080
SIM_URL ?= http://localhost:5174
ARGS ?=

ifeq ($(OS),Windows_NT)
  VENV_PY := .venv/Scripts/python.exe
  SYS_PY := python
else
  VENV_PY := .venv/bin/python
  SYS_PY := python3
endif
PY ?= $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(SYS_PY))

COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

.PHONY: help venv install dev-relay dev-app sim test test-relay test-app seed eval latency \
        deploy deploy-remote logs health

help:
	@echo targets: install dev-relay dev-app sim test seed eval latency deploy deploy-remote logs health

venv:
	$(SYS_PY) -m venv .venv

install:
	$(PY) -m pip install -e "relay[dev]"

dev-relay:
	$(PY) -m uvicorn margin_relay.main:create_app --factory --reload --reload-dir relay/src --host 0.0.0.0 --port $(PORT)

dev-app:
	cd app && npm run dev

sim:
	cd app && npx evenhub-simulator $(SIM_URL)

test: test-relay test-app

test-relay:
	$(PY) -m pytest relay/tests -q

test-app:
ifneq ($(wildcard app/package.json),)
	cd app && npm test
else
	@echo app/ not merged on this branch - skipping app tests
endif

seed:
	$(PY) db/seed.py $(ARGS)

eval:
	$(PY) eval/run_eval.py $(ARGS)

latency:
	$(PY) -m margin_relay.latency $(ARGS)

deploy:
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

deploy-remote:
	ssh $(VM_HOST) "cd margin && git pull --ff-only && make deploy"

logs:
	$(COMPOSE) logs -f --tail=200 relay

# make health URL=https://margin.<domain>
URL ?= http://localhost:$(PORT)
health:
	$(PY) deploy/healthcheck.py --url $(URL)/v1/health --verbose
