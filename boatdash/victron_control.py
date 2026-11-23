"""Switch a Victron solar charger on/off over Bluetooth (VE.Smart, like VictronConnect).

Each operation is one short session: connect (paired with the device PIN), write/read register
0x0200 (device mode), disconnect. Staying disconnected leaves the device free for the phone app.
The mode is read at start-up, after every change and every ``refresh_s``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ble import BleHub
from .vesmart import Link, Session, VeSmartError, deepest_instance

log = logging.getLogger(__name__)

DEFAULT_PINS_FILE = Path.home() / ".config" / "boatdash" / "victron-pins.json"

VREG_DEVICE_MODE = 0x0200  # 1 on, 4 off, 5 eco (VE.Direct HEX)
VREG_REMOTE_CONTROL_USED = 0x0202  # bit 1 must be set for 0x0200 to be honoured
MODES = {1: "on", 4: "off", 5: "eco"}
RAW = {"on": b"\x01", "off": b"\x04"}

Connector = Callable[[str, str], AbstractAsyncContextManager[Link]]


def load_pins(path: Path | None = None) -> dict[str, str]:
    """{MAC: PIN} from the private file (never in the repo)."""
    path = path or Path(os.environ.get("BOATDASH_VICTRON_PINS", DEFAULT_PINS_FILE))
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return {str(mac).upper(): str(pin) for mac, pin in raw.items()}


@dataclass
class ControlState:
    mode: str | None = None  # "on" / "off" / "eco" / None (unknown yet)
    busy: bool = False
    error: str | None = None  # last failure, cleared by the next success
    checked: float | None = None  # unix time of the last confirmed read

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Busy(Exception):
    """Another operation on this device is running."""


class ChargerControl:
    def __init__(
        self,
        name: str,
        address: str,
        pin: str,
        connect: Connector,
        refresh_s: float = 1800.0,
        attempts: int = 3,
    ) -> None:
        self.name = name
        self.address = address.upper()
        self.pin = pin
        self._connect = connect
        self.refresh_s = refresh_s
        self.attempts = attempts
        self.state = ControlState()
        self._lock = asyncio.Lock()

    async def _session(self, op: Callable[[Session, int], Any]) -> Any:
        """Run ``op`` in a fresh session, retrying the whole session (BLE links are flaky)."""
        last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                async with self._connect(self.address, self.pin) as link:
                    session = Session(link)
                    await session.open()
                    instance = deepest_instance(await session.devices())
                    return await op(session, instance)
            except VeSmartError:  # the device answered: retrying won't change it
                raise
            except Exception as exc:
                last = exc
                log.warning("%s: session attempt %d failed: %r", self.name, attempt + 1, exc)
                await asyncio.sleep(2 * (attempt + 1))
        raise ConnectionError(f"device unreachable: {last!r}")

    async def _run(self, op: Callable[[Session, int], Any]) -> str:
        if self._lock.locked():
            raise Busy(self.name)
        async with self._lock:
            self.state.busy = True
            try:
                raw: bytes = await self._session(op)
            except Exception as exc:
                self.state.error = "refused" if isinstance(exc, VeSmartError) else "unreachable"
                log.error("%s: %s", self.name, exc)
                raise
            finally:
                self.state.busy = False
            self.state.mode = MODES.get(raw[0], f"unknown_{raw[0]}") if raw else None
            self.state.error = None
            self.state.checked = time.time()
            return self.state.mode or "unknown"

    async def refresh(self) -> str:
        async def op(s: Session, i: int) -> bytes:
            return await s.read(i, VREG_DEVICE_MODE)

        return await self._run(op)

    async def set_mode(self, on: bool) -> str:
        raw = RAW["on" if on else "off"]

        async def op(s: Session, i: int) -> bytes:
            remote = await s.read(i, VREG_REMOTE_CONTROL_USED)
            if not (int.from_bytes(remote, "little") & 0x02):
                raise VeSmartError("remote on/off is disabled on the device (0x0202 bit 1)")
            await s.write(i, VREG_DEVICE_MODE, raw)
            return raw

        log.info("%s: switching %s", self.name, "ON" if on else "OFF")
        return await self._run(op)

    async def run(self, start_delay: float = 15.0) -> None:
        """Keep the displayed mode fresh (it can also be changed from the phone app)."""
        await asyncio.sleep(start_delay)
        while True:
            try:
                await self.refresh()
            except Busy:
                pass
            except Exception as exc:
                log.warning("%s: mode refresh failed: %r", self.name, exc)
            await asyncio.sleep(self.refresh_s)


# ---- production link: bleak + BlueZ pairing agent ------------------------------------------
class _BleakLink:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def read(self, uuid: str) -> bytes:
        return bytes(await self._client.read_gatt_char(uuid))

    async def write(self, uuid: str, data: bytes) -> None:
        await self._client.write_gatt_char(uuid, data, response=False)

    async def start_notify(self, uuid: str, callback: Callable[[bytes], None]) -> None:
        await self._client.start_notify(uuid, lambda _char, data: callback(bytes(data)))


def bleak_connector(hub: BleHub) -> Connector:  # pragma: no cover - needs a real adapter
    @asynccontextmanager
    async def connect(address: str, pin: str) -> AsyncIterator[Link]:
        from bleak import BleakClient

        from .bluez_agent import PasskeyAgent

        async with asyncio.timeout(60):
            device = await hub.wait_for_device(address)  # connect via the shared scanner
        async with PasskeyAgent(pin), BleakClient(device, timeout=20) as client:
            await client.pair()  # no-op once bonded
            yield _BleakLink(client)

    return connect
