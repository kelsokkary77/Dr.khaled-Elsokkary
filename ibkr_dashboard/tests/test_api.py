"""End-to-end checks over the HTTP surface, using the demo provider."""

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.providers import ProviderError, describe_providers, get_provider
from backend.service import DashboardService
from backend.store import SnapshotStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    from backend import main

    settings = Settings(provider="demo", db_path=tmp_path / "api.sqlite3")
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        main, "service", DashboardService(settings, SnapshotStore(settings.db_path))
    )
    return TestClient(main.app)


def test_health_reports_an_empty_cache_before_any_sync(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["has_data"] is False


def test_sync_then_health_reports_data(client):
    assert client.post("/api/sync").json()["ok"] is True
    assert client.get("/api/health").json()["has_data"] is True


def test_sync_reports_what_it_pulled(client):
    body = client.post("/api/sync").json()
    assert body["provider"] == "demo"
    assert body["positions"] > 0 and body["nav_points"] > 0
    assert any("sample portfolio" in w for w in body["warnings"])


def test_dashboard_auto_syncs_on_a_cold_cache(client):
    body = client.get("/api/dashboard").json()
    assert body["summary"]["net_liquidation"] > 0
    assert len(body["positions"]) > 0


def test_dashboard_payload_has_every_section(client):
    body = client.get("/api/dashboard").json()
    assert {
        "summary", "positions", "cash", "trades", "allocation", "concentration",
        "movers", "nav", "activity", "warnings", "base_currency", "storage",
    } <= set(body)


def test_position_weights_sum_to_one_hundred(client):
    positions = client.get("/api/positions").json()["positions"]
    assert sum(p["weight_pct"] for p in positions) == pytest.approx(100.0, abs=0.01)


@pytest.mark.parametrize("path", ["/api/nav", "/api/allocation", "/api/trades", "/api/providers"])
def test_sub_routes_return_200(client, path):
    assert client.get(path).status_code == 200


def test_trades_respects_the_limit(client):
    assert len(client.get("/api/trades?limit=3").json()["trades"]) == 3


def test_trade_limit_is_validated(client):
    assert client.get("/api/trades?limit=0").status_code == 422


def test_unknown_provider_is_rejected_with_a_helpful_message(client):
    body = client.post("/api/sync?provider=nope").json()
    assert "Unknown provider" in body["error"]
    assert "demo" in body["error"]


def test_unconfigured_flex_explains_the_missing_setting(client):
    body = client.post("/api/sync?provider=flex").json()
    assert "IBKR_FLEX_TOKEN" in body["error"]


def test_a_failed_sync_is_recorded_in_the_log(client):
    client.post("/api/sync?provider=flex")
    assert client.get("/api/health").json()["last_sync"]["ok"] == 0


def test_index_and_static_assets_are_served(client):
    assert "IBKR Portfolio Dashboard" in client.get("/").text
    for asset in ("app.js", "charts.js", "styles.css"):
        assert client.get(f"/static/{asset}").status_code == 200


def test_repeated_syncs_do_not_multiply_nav_rows(client):
    first = client.post("/api/sync").json()["nav_points"]
    client.post("/api/sync")
    assert client.get("/api/dashboard").json()["storage"]["nav_points"] == first


def test_provider_registry_lists_all_three(client):
    names = {p["name"] for p in client.get("/api/providers").json()["providers"]}
    assert names == {"demo", "flex", "cpapi"}


def test_flex_setup_instructions_are_exposed(client):
    steps = client.get("/api/providers").json()["flex_setup"]
    assert any("Flex Web Service" in s for s in steps)


# ------------------------------------------------------------ service layer


def test_unknown_provider_raises_provider_error(settings):
    with pytest.raises(ProviderError, match="Unknown provider"):
        get_provider(settings, "nope")


def test_describe_providers_marks_the_selected_one(settings):
    rows = describe_providers(settings)
    assert [r["name"] for r in rows if r["selected"]] == ["demo"]


def test_dashboard_without_data_and_without_sync_raises(settings, tmp_path):
    service = DashboardService(settings, SnapshotStore(tmp_path / "x.sqlite3"))
    with pytest.raises(ProviderError, match="No data cached"):
        service.dashboard(allow_sync=False)


def test_stored_nav_history_outlives_a_single_snapshot(settings, tmp_path):
    """A cpapi-style point-in-time sync accumulates into a real series."""
    from backend.models import AccountSummary, NavPoint, PortfolioSnapshot

    store = SnapshotStore(tmp_path / "hist.sqlite3")
    service = DashboardService(settings, store)
    for day, nav in [("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 120.0)]:
        store.save_snapshot(
            PortfolioSnapshot(
                provider="cpapi",
                summary=AccountSummary(account_id="U1", net_liquidation=nav),
                nav_history=[NavPoint(day, nav)],
            )
        )
    payload = service.dashboard(allow_sync=False)
    assert payload["nav"]["observations"] == 3
    assert payload["nav"]["total_return_pct"] == pytest.approx(20.0)
