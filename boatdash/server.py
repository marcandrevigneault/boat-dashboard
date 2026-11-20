"""Boat dashboard web server: polls BMS devices and serves the UI.

Run: .venv/bin/python -m boatdash.server
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .jbd import JBDClient

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

batteries = [
    JBDClient(b["name"], b["address"], CONFIG.get("poll_interval", 2.0))
    for b in CONFIG["batteries"] if b.get("type", "jbd") == "jbd"
]


def snapshot() -> dict:
    return {"batteries": [b.state.to_dict() for b in batteries]}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = []
    for b in batteries:
        tasks.append(asyncio.create_task(b.run()))
        await asyncio.sleep(1.5)  # stagger BLE connects; BlueZ dislikes simultaneous ones
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Boat Dashboard", lifespan=lifespan)


@app.get("/api/batteries")
def api_batteries() -> dict:
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
