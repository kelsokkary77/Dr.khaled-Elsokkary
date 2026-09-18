"""FastAPI app: JSON API plus the static dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import REPO_ROOT, load_settings
from .providers import ProviderError, describe_providers
from .providers.flex import describe_setup as flex_setup
from .service import DashboardService

FRONTEND_DIR = REPO_ROOT / "frontend"

settings = load_settings()
service = DashboardService(settings)

app = FastAPI(
    title="IBKR Portfolio Dashboard",
    version="1.0.0",
    description=(
        "Syncs an Interactive Brokers account into tables and charts. "
        "Data sources: built-in demo, Flex Web Service, or the Client Portal Gateway."
    ),
)


def _fail(exc: ProviderError, status_code: int = 502) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": str(exc), "provider": settings.provider},
    )


# --------------------------------------------------------------------- routes


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, **service.status()}


@app.get("/api/providers", tags=["meta"])
def providers() -> dict[str, Any]:
    return {
        "selected": settings.provider,
        "providers": describe_providers(settings),
        "flex_setup": list(flex_setup()),
        "cpapi_base_url": settings.cpapi_base_url,
    }


@app.post("/api/sync", tags=["data"])
def sync(
    provider: str | None = Query(
        default=None,
        description="Override the configured provider for this sync only.",
    )
) -> Any:
    try:
        snapshot = service.sync(provider)
    except ProviderError as exc:
        return _fail(exc)
    return {
        "ok": True,
        "provider": snapshot.provider,
        "fetched_at": snapshot.fetched_at,
        "positions": len(snapshot.positions),
        "nav_points": len(snapshot.nav_history),
        "trades": len(snapshot.trades),
        "warnings": snapshot.warnings,
    }


@app.get("/api/dashboard", tags=["data"])
def dashboard(
    refresh: bool = Query(
        default=False, description="Pull from IBKR before rendering."
    )
) -> Any:
    try:
        if refresh:
            service.sync()
        return service.dashboard()
    except ProviderError as exc:
        return _fail(exc)


@app.get("/api/positions", tags=["data"])
def positions() -> Any:
    try:
        return {"positions": service.dashboard(allow_sync=True)["positions"]}
    except ProviderError as exc:
        return _fail(exc)


@app.get("/api/nav", tags=["data"])
def nav() -> Any:
    try:
        return service.dashboard(allow_sync=True)["nav"]
    except ProviderError as exc:
        return _fail(exc)


@app.get("/api/allocation", tags=["data"])
def allocation() -> Any:
    try:
        return service.dashboard(allow_sync=True)["allocation"]
    except ProviderError as exc:
        return _fail(exc)


@app.get("/api/trades", tags=["data"])
def trades(limit: int = Query(default=200, ge=1, le=5000)) -> Any:
    try:
        data = service.dashboard(allow_sync=True)
        return {"trades": data["trades"][:limit], "activity": data["activity"]}
    except ProviderError as exc:
        return _fail(exc)


# ------------------------------------------------------------------- frontend


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    page = FRONTEND_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=500, detail="frontend/index.html is missing")
    return FileResponse(page)


if FRONTEND_DIR.is_dir():
    app.mount(
        "/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static"
    )


def run() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover
    run()
