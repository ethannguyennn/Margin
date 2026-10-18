# Margin -- team build contract. Works with GNU make on Linux/macOS and
# mingw32-make / GNU make on Windows (no shell-specific syntax in recipes).
#
#   make install     # one-time: venv deps for the relay (+ dev/test tools)
#   make dev-relay   # uvicorn, reload, MOCK_MODE from .env, bound to 0.0.0.0 for LAN sideload
#   make dev-app     # the Even Hub app on :5174 (lens + phone screen; a browser shows the phone screen)
#   make sim         # even simulator against the dev app
#   make test        # pytest relay/tests + app tests + app typecheck/build (must stay green)
#   make pack        # build app/margin.ehpk for Even Hub
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

.PHONY: help venv install dev-relay dev-app sim test test-relay test-app pack \
        seed eval latency deploy deploy-remote logs health sync-branches

help:
	@echo targets: install dev-relay dev-app sim test pack seed eval latency deploy deploy-remote logs health

venv:
	$(SYS_PY) -m venv .venv

install:
	$(PY) -m pip install -e "relay[dev]"
ifneq ($(wildcard app/package.json),)
	cd app && npm ci
endif

dev-relay:
	$(PY) -m uvicorn margin_relay.main:create_app --factory --reload --reload-dir relay/src --host 0.0.0.0 --port $(PORT)

dev-app:
	cd app && npm run dev

sim:
	cd app && npx evenhub-simulator $(SIM_URL)

pack:
	cd app && npm run pack

test: test-relay test-app

test-relay:
	$(PY) -m pytest relay/tests -q

# Unit tests, then typecheck + production build (lens and phone screen).
test-app:
ifneq ($(wildcard app/package.json),)
	cd app && npm test
	cd app && npm run build
else
	@echo app/ not merged on this branch - skipping app tests
endif

seed:
	$(PY) db/seed.py $(ARGS)

# Against the running relay; add ARGS=--allow-mock for a MOCK_MODE=1 relay.
EVAL_URL ?= http://127.0.0.1:$(PORT)
eval:
	$(PY) eval/run_eval.py --base-url $(EVAL_URL) $(ARGS)

latency:
	$(PY) -m margin_relay.latency $(ARGS)

deploy:
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

deploy-remote:
	ssh $(VM_HOST) "cd margin && git pull --ff-only && make deploy"

logs:
	$(COMPOSE) logs -f --tail=200 relay

# Read-only, detached checkouts of every team branch under _branches/ (gitignored),
# refreshed from origin. For browsing (e.g. in Obsidian); never commit in them.
BRANCHES := part-1-lens-hands-free-ui part-2-motion-voice-io part-3-relay-platform part-4-conversion-diagrams part-5-portal-data
sync-branches:
	git fetch origin --prune
	git worktree prune
	$(foreach b,$(BRANCHES),$(if $(wildcard _branches/$(b)/.git),git -C _branches/$(b) checkout --detach --force origin/$(b),git worktree add --detach _branches/$(b) origin/$(b))$(\n))

define \n


endef

# make health URL=https://getyourassto.work
URL ?= http://localhost:$(PORT)
health:
	$(PY) deploy/healthcheck.py --url $(URL)/v1/health --verbose
