"""Relay configuration. Every value comes from the environment (or the repo-root .env).

Owned by Part 3. Parts 4 and 5 read settings through ``get_settings()`` and never
touch ``os.environ`` directly. Need a new variable? Ask in the channel.

Secrets are ``SecretStr`` so they never show up in a repr, a log line or a Sentry
event by accident. Read them with ``settings.gemini_api_key.get_secret_value()``.

No model IDs are hardcoded here: every ``GEMINI_MODEL_*`` defaults to empty and
must be set in .env from Google's current model list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# relay/src/specs_relay/config.py -> repo root is three levels above the package dir.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        # `KEY=` in .env means "unset", so optional floats/ints fall back to their default.
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # --- Gemini (Part 4 consumes) ---------------------------------------------
    gemini_api_key: SecretStr | None = None
    gemini_model_generate: str = ""
    gemini_model_transcribe: str = ""
    gemini_model_embed: str = ""
    gemini_model_convert: str = ""  # v2: material extraction + structuring (Part 4 picks)
    embed_dim: int = 768

    # --- Tiger Cloud / Postgres (Part 5 consumes) -----------------------------
    database_url: SecretStr | None = None
    database_url_fork: SecretStr | None = None
    enable_revision_fork: bool = False

    # --- Sentry ---------------------------------------------------------------
    sentry_dsn_relay: str = ""
    sentry_dsn_app: str = ""  # public DSN, consumed by the app build, not the relay
    sentry_environment: str = "dev"
    sentry_traces_sample_rate: float = 1.0

    # --- Notifier (Part 5 consumes) -------------------------------------------
    notifier: str = "console"  # console | photon
    photon_api_key: SecretStr | None = None
    supervisor_address: str = ""

    # --- Retrieval thresholds (Part 4 tunes) ----------------------------------
    not_found_min_sim: float | None = None
    not_found_min_rrf: float | None = None

    # --- Server ---------------------------------------------------------------
    public_origin: str = ""
    allowed_origins: str = ""  # comma-separated, exact origins
    allowed_origin_regex: str = ""  # optional, e.g. LAN dev servers
    mock_mode: bool = False
    max_audio_seconds: float = 8.0
    admin_token: SecretStr | None = None
    corpus_dir: str = ""  # default: <repo>/corpus

    # --- v2 portal, devices, uploads, conversion --------------------------------
    portal_token: SecretStr | None = None  # one shared supervisor token; empty = portal off
    max_upload_mb: int = 20
    convert_timeout_s: float = 180.0
    convert_concurrency: int = 2
    pair_code_ttl_s: int = 15 * 60
    pair_rate_per_min: int = 10  # POST /v1/devices/pair per client IP
    # Latency budget. ASK_BUDGET_S is the whole /v1/ask (speech, retrieval, up to two
    # Gemini attempts) and must stay under the app's VITE_ASK_TIMEOUT_MS (8000), or the
    # lens gives up before the answer arrives. The per-call guards below are capped by
    # whatever budget is left; the Gemini clients time out 0.5 s inside them.
    ask_budget_s: float = 7.5
    stt_timeout_s: float = 4.5
    generate_timeout_s: float = 6.5
    log_level: str = "INFO"
    git_sha: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
