# Margin -- team build contract. Works with GNU make on Linux/macOS and
# mingw32-make / GNU make on Windows (no shell-specific syntax in recipes).
#
#   make install     # one-time: venv deps for the relay (+ dev/test tools)
#   make dev-relay   # uvicorn, reload, MOCK_MODE from .env, bound to 0.0.0.0 for LAN sideload
#   make dev-app     # cd app && npm run dev
#   make dev-ios     # iPhone companion web app on :5175
#   make sim         # even simulator against the dev app
#   make dev-portal  # employer portal dev server (Part 5), proxies /v1 to the relay on :8080
#   make test        # relay + app + ios + portal (must stay green)
#   make seed        # python db/seed.py            (Part 5)
#   make eval        # python eval/run_eval.py      (Part 5)
#   make eval-conversion  # material -> procedure eval, 0 fabricated values (Part 4)
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

.PHONY: help venv install dev-relay dev-app dev-ios dev-portal sim test test-relay test-app \
        test-ios test-portal seed eval eval-conversion latency deploy deploy-remote logs health \
        sync-branches

help:
	@echo targets: install dev-relay dev-app dev-ios dev-portal sim test seed eval eval-conversion latency deploy deploy-remote logs health

venv:
	$(SYS_PY) -m venv .venv

install:
	$(PY) -m pip install -e "relay[dev]"
ifneq ($(wildcard app/package.json),)
	cd app && npm ci
endif
ifneq ($(wildcard ios/package.json),)
	cd ios && npm ci
endif
ifneq ($(wildcard portal/package.json),)
	cd portal && npm ci
endif

dev-relay:
	$(PY) -m uvicorn margin_relay.main:create_app --factory --reload --reload-dir relay/src --host 0.0.0.0 --port $(PORT)

dev-app:
	cd app && npm run dev

# iPhone companion on :5175 (needs VITE_RELAY_ORIGIN, see ios/.env.example)
dev-ios:
	cd ios && npm run dev

sim:
	cd app && npx evenhub-simulator $(SIM_URL)

# The portal's dev server proxies /v1 to the relay on :8080 (start `make dev-relay` too).
dev-portal:
	cd portal && npm run dev

test: test-relay test-app test-ios test-portal

test-relay:
	$(PY) -m pytest relay/tests -q

test-app:
ifneq ($(wildcard app/package.json),)
	cd app && npm test
else
	@echo app/ not merged on this branch - skipping app tests
endif

# The iPhone companion has no unit tests yet: typecheck + production build.
test-ios:
ifneq ($(wildcard ios/package.json),)
	cd ios && npm run build
else
	@echo ios/ not merged on this branch - skipping companion checks
endif

test-portal:
ifneq ($(wildcard portal/package.json),)
	cd portal && npm test
else
	@echo portal/ not merged on this branch - skipping portal tests
endif

seed:
	$(PY) db/seed.py $(ARGS)

# Against the running relay; add ARGS=--allow-mock for a MOCK_MODE=1 relay.
EVAL_URL ?= http://127.0.0.1:$(PORT)
eval:
	$(PY) eval/run_eval.py --base-url $(EVAL_URL) $(ARGS)

# Part 4's conversion eval: runs extract -> convert -> verify_step -> render directly (no
# HTTP) and exits non-zero if any *passing* step contains a fabricated value.
eval-conversion:
ifneq ($(wildcard eval/conversion/run_conversion_eval.py),)
	$(PY) eval/conversion/run_conversion_eval.py $(ARGS)
else
	@echo eval/conversion/run_conversion_eval.py not merged on this branch yet - Part 4
endif

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
