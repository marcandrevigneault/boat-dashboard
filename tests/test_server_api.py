"""HTTP API for the solar on/off control (lifespan not started: no Bluetooth)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_vesmart import FakeDevice, connector

from boatdash import server
from boatdash.victron_control import ChargerControl


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeDevice]:
    dev = FakeDevice(mode=1)
    control = ChargerControl("SmartSolar", "E3:E4:87:F8:EB:A1", "000000", connector(dev))  # type: ignore[arg-type]
    monkeypatch.setattr(server, "controls", {"SmartSolar": control})
    return TestClient(server.app), dev


def test_switch_off_then_on(client: tuple[TestClient, FakeDevice]) -> None:
    http, dev = client
    r = http.post("/api/victron/SmartSolar/charger", json={"on": False})
    assert r.status_code == 200 and r.json() == {"name": "SmartSolar", "mode": "off"}
    assert dev.regs[(3, 0x0200)] == b"\x04"
    assert http.post("/api/victron/SmartSolar/charger", json={"on": True}).json()["mode"] == "on"


def test_unknown_device_and_bad_body(client: tuple[TestClient, FakeDevice]) -> None:
    http, _ = client
    assert http.post("/api/victron/Nope/charger", json={"on": True}).status_code == 404
    assert http.post("/api/victron/SmartSolar/charger", json={}).status_code == 422


def test_refused_switch_reports_502(client: tuple[TestClient, FakeDevice]) -> None:
    http, dev = client
    dev.refuse = True
    r = http.post("/api/victron/SmartSolar/charger", json={"on": False})
    assert r.status_code == 502 and r.json()["detail"] == "refused"


def test_snapshot_carries_control_state(client: tuple[TestClient, FakeDevice]) -> None:
    http, _ = client
    snap = http.get("/api/batteries").json()
    solar = [d for d in snap["victron"] if d["name"] == "SmartSolar"]
    assert solar and solar[0]["control"] == {
        "mode": None,
        "busy": False,
        "error": None,
        "checked": None,
    }
