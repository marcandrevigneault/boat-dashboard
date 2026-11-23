"""Boat dashboard web server: polls BMS devices and serves the UI.

Run: .venv/bin/python -m boatdash.server
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ble import BleHub
from .jbd import JBDClient
from .victron import VictronMonitor, load_keys
from .victron_control import Busy, ChargerControl, bleak_connector, load_pins

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

hub = BleHub()

batteries = [
    JBDClient(b["name"], b["address"], CONFIG.get("poll_interval", 2.0), hub=hub)
    for b in CONFIG["batteries"]
    if b.get("type", "jbd") == "jbd"
]


victron = VictronMonitor(
    [(d["name"], d["address"], d["kind"]) for d in CONFIG.get("victron", [])],
    load_keys(),
)
hub.add_listener(victron.on_advertisement)

# On/off control for solar chargers whose Bluetooth PIN is in the private pins file.
_pins = load_pins()
controls = {
    d["name"]: ChargerControl(
        d["name"], d["address"], _pins[d["address"].upper()], bleak_connector(hub)
    )
    for d in CONFIG.get("victron", [])
    if d["kind"] == "solar" and d["address"].upper() in _pins
}


def snapshot() -> dict[str, Any]:
    return {
        "batteries": [b.state.to_dict() for b in batteries],
        "victron": [
            {**d, "control": controls[d["name"]].state.to_dict()} if d["name"] in controls else d
            for d in victron.snapshot()
        ],
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    tasks = [asyncio.create_task(hub.run())]
    for b in batteries:
        tasks.append(asyncio.create_task(b.run()))
        await asyncio.sleep(1.5)  # stagger BLE connects; BlueZ dislikes simultaneous ones
    tasks.extend(asyncio.create_task(c.run()) for c in controls.values())
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Boat Dashboard", lifespan=lifespan)


@app.get("/api/batteries")
def api_batteries() -> dict[str, Any]:
    return snapshot()


class ChargerCommand(BaseModel):
    on: bool


@app.post("/api/victron/{name}/charger")
async def api_charger(name: str, cmd: ChargerCommand) -> dict[str, Any]:
    """Switch a solar charger on/off; answers once the device confirmed the new mode."""
    control = controls.get(name)
    if control is None:
        raise HTTPException(404, "no on/off control for this device")
    try:
        mode = await control.set_mode(cmd.on)
    except Busy:
        raise HTTPException(409, "another command is running") from None
    except Exception as exc:
        raise HTTPException(502, control.state.error or "failed") from exc
    return {"name": name, "mode": mode}


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    try:
        while True:
            await socket.send_json(snapshot())
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        pass


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")


if __name__ == "__main__":
    # "" = every interface, IPv4 and IPv6 (asyncio opens one socket per family; "::" would be
    # IPv6-only). The router gives the hostname IPv6 addresses too, and phones try those first.
    uvicorn.run(app, host=CONFIG.get("http_host", ""), port=CONFIG.get("http_port", 8080))
