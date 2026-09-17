"""Runtime configuration, read from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "ibkr.sqlite3"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overwriting real env vars."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_list(key: str) -> list[str]:
    raw = os.environ.get(key, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """All tunables in one place. Every field has a working default."""

    # Which data source feeds the dashboard: "demo" | "flex" | "cpapi".
    provider: str = "demo"

    # --- IBKR Flex Web Service (read-only, no gateway required) ---
    flex_token: str = ""
    flex_query_ids: list[str] = field(default_factory=list)
    flex_base_url: str = (
        "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
    )
    flex_version: str = "3"
    # IBKR generates the statement asynchronously; we poll GetStatement.
    flex_poll_attempts: int = 12
    flex_poll_seconds: int = 5

    # --- IBKR Client Portal Web API (local gateway, live data) ---
    cpapi_base_url: str = "https://localhost:5000/v1/api"
    # The gateway ships a self-signed certificate. Only relax verification for
    # loopback addresses -- never for a remote host.
    cpapi_verify_ssl: bool = False
    cpapi_account_id: str = ""
    cpapi_timeout_seconds: int = 30

    # --- Server / storage ---
    host: str = "127.0.0.1"
    port: int = 8787
    db_path: Path = DEFAULT_DB_PATH
    base_currency: str = "USD"
    # Auto-sync on first page load when the cache is empty.
    autosync_on_start: bool = True

    @property
    def cpapi_is_loopback(self) -> bool:
        return any(
            host in self.cpapi_base_url for host in ("localhost", "127.0.0.1", "[::1]")
        )

    @property
    def effective_verify_ssl(self) -> bool:
        """Never silently disable TLS verification for a non-loopback host."""
        if self.cpapi_is_loopback:
            return self.cpapi_verify_ssl
        return True


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or (REPO_ROOT / ".env"))

    db_path = Path(os.environ.get("IBKR_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()

    return Settings(
        provider=os.environ.get("IBKR_PROVIDER", "demo").strip().lower(),
        flex_token=os.environ.get("IBKR_FLEX_TOKEN", "").strip(),
        flex_query_ids=_env_list("IBKR_FLEX_QUERY_IDS"),
        flex_base_url=os.environ.get(
            "IBKR_FLEX_BASE_URL",
            "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService",
        ).rstrip("/"),
        flex_version=os.environ.get("IBKR_FLEX_VERSION", "3"),
        flex_poll_attempts=_env_int("IBKR_FLEX_POLL_ATTEMPTS", 12),
        flex_poll_seconds=_env_int("IBKR_FLEX_POLL_SECONDS", 5),
        cpapi_base_url=os.environ.get(
            "IBKR_CPAPI_BASE_URL", "https://localhost:5000/v1/api"
        ).rstrip("/"),
        cpapi_verify_ssl=_env_bool("IBKR_CPAPI_VERIFY_SSL", False),
        cpapi_account_id=os.environ.get("IBKR_CPAPI_ACCOUNT_ID", "").strip(),
        cpapi_timeout_seconds=_env_int("IBKR_CPAPI_TIMEOUT_SECONDS", 30),
        host=os.environ.get("IBKR_HOST", "127.0.0.1"),
        port=_env_int("IBKR_PORT", 8787),
        db_path=db_path,
        base_currency=os.environ.get("IBKR_BASE_CURRENCY", "USD").upper(),
        autosync_on_start=_env_bool("IBKR_AUTOSYNC_ON_START", True),
    )
