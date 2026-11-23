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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .ble import BleHub
from .jbd import JBDClient
from .victron import VictronMonitor, load_keys

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


def snapshot() -> dict[str, Any]:
    return {
        "batteries": [b.state.to_dict() for b in batteries],
        "victron": victron.snapshot(),
    }


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    tasks = [asyncio.create_task(hub.run())]
    for b in batteries:
        tasks.append(asyncio.create_task(b.run()))
        await asyncio.sleep(1.5)  # stagger BLE connects; BlueZ dislikes simultaneous ones
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Boat Dashboard", lifespan=lifespan)


@app.get("/api/batteries")
def api_batteries() -> dict[str, Any]:
    return snapshot()


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
    uvicorn.run(app, host="0.0.0.0", port=CONFIG.get("http_port", 8080))
