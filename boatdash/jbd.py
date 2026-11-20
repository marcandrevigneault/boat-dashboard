"""Bluetooth LE client for JBD / Xiaoxiang-style battery management systems.

These BMS advertise service 0xFF00. We write requests to 0xFF02 and the
replies come back as notifications on 0xFF01, possibly split across packets.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from bleak import BleakClient

log = logging.getLogger(__name__)

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

CMD_BASIC_INFO = 0x03
CMD_CELL_VOLTAGES = 0x04

# Protection status bits (register 0x03, bytes 16-17)
PROTECTION_FLAGS = [
    "cell_overvoltage",
    "cell_undervoltage",
    "pack_overvoltage",
    "pack_undervoltage",
    "charge_overtemp",
    "charge_undertemp",
    "discharge_overtemp",
    "discharge_undertemp",
    "charge_overcurrent",
    "discharge_overcurrent",
    "short_circuit",
    "frontend_ic_error",
    "mosfet_locked",
]


def build_read_request(register: int) -> bytes:
    checksum = (0x10000 - register) & 0xFFFF  # sum of register + length(0), negated
    return bytes([0xDD, 0xA5, register, 0x00, checksum >> 8, checksum & 0xFF, 0x77])


def verify_frame(frame: bytes) -> bytes:
    """Check a complete response frame and return its payload."""
    if len(frame) < 7 or frame[0] != 0xDD or frame[-1] != 0x77:
        raise ValueError(f"bad frame framing: {frame.hex()}")
    status, length = frame[2], frame[3]
    payload = frame[4 : 4 + length]
    if len(payload) != length or len(frame) != length + 7:
        raise ValueError(f"bad frame length: {frame.hex()}")
    if status != 0x00:
        raise ValueError(f"BMS returned error status {status:#x}")
    expected = (0x10000 - (length + sum(payload))) & 0xFFFF
    got = int.from_bytes(frame[4 + length : 6 + length], "big")
    if expected != got:
        raise ValueError(f"checksum mismatch {got:#x} != {expected:#x}")
    return payload


def _u16(b: bytes, i: int) -> int:
    return int.from_bytes(b[i : i + 2], "big")


def _s16(b: bytes, i: int) -> int:
    return int.from_bytes(b[i : i + 2], "big", signed=True)


@dataclass
class BatteryState:
    name: str
    address: str
    connected: bool = False
    voltage: float | None = None  # V
    current: float | None = None  # A, positive = charging
    power: float | None = None  # W
    soc: int | None = None  # %
    remaining_ah: float | None = None
    capacity_ah: float | None = None
    cycles: int | None = None
    temperatures: list[float] = field(default_factory=list)  # °C
    cells: list[float] = field(default_factory=list)  # V
    charge_enabled: bool | None = None
    discharge_enabled: bool | None = None
    protections: list[str] = field(default_factory=list)
    updated: float | None = None  # unix time of last good reading
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.cells:
            d["cell_min"] = min(self.cells)
            d["cell_max"] = max(self.cells)
            d["cell_delta_mv"] = round((max(self.cells) - min(self.cells)) * 1000)
        return d


def parse_basic_info(p: bytes, state: BatteryState) -> None:
    state.voltage = _u16(p, 0) / 100
    state.current = _s16(p, 2) / 100
    state.power = round(state.voltage * state.current, 1)
    state.remaining_ah = _u16(p, 4) / 100
    state.capacity_ah = _u16(p, 6) / 100
    state.cycles = _u16(p, 8)
    prot = _u16(p, 16)
    state.protections = [n for i, n in enumerate(PROTECTION_FLAGS) if prot & (1 << i)]
    state.soc = p[19]
    fet = p[20]
    state.charge_enabled = bool(fet & 0x01)
    state.discharge_enabled = bool(fet & 0x02)
    ntc_count = p[22]
    state.temperatures = [
        round((_u16(p, 23 + 2 * i) - 2731) / 10, 1)
        for i in range(ntc_count)
        if 23 + 2 * i + 2 <= len(p)
    ]


def parse_cell_voltages(p: bytes, state: BatteryState) -> None:
    state.cells = [_u16(p, i) / 1000 for i in range(0, len(p) - 1, 2)]


class JBDClient:
    """Keeps a connection to one BMS and polls it, reconnecting as needed."""

    def __init__(self, name: str, address: str, interval: float = 2.0):
        self.state = BatteryState(name=name, address=address)
        self.interval = interval
        self._buf = bytearray()
        self._frame: asyncio.Future[bytes] | None = None

    def _on_notify(self, _char: object, data: bytearray) -> None:
        if data[:1] == b"\xdd":
            self._buf = bytearray()
        self._buf += data
        # Complete when we have header + payload + checksum + end byte.
        if len(self._buf) >= 4 and len(self._buf) >= self._buf[3] + 7:
            if self._frame and not self._frame.done():
                self._frame.set_result(bytes(self._buf))
            self._buf = bytearray()

    async def _request(self, client: BleakClient, register: int) -> bytes:
        self._frame = asyncio.get_running_loop().create_future()
        self._buf = bytearray()
        await client.write_gatt_char(WRITE_UUID, build_read_request(register), response=False)
        frame = await asyncio.wait_for(self._frame, timeout=5)
        return verify_frame(frame)

    async def read_once(self, client: BleakClient) -> None:
        parse_basic_info(await self._request(client, CMD_BASIC_INFO), self.state)
        parse_cell_voltages(await self._request(client, CMD_CELL_VOLTAGES), self.state)
        self.state.updated = time.time()
        self.state.error = None

    async def run(self) -> None:
        backoff = 2.0
        while True:
            try:
                log.info("connecting to %s (%s)", self.state.name, self.state.address)
                async with BleakClient(self.state.address, timeout=20) as client:
                    await client.start_notify(NOTIFY_UUID, self._on_notify)
                    self.state.connected = True
                    backoff = 2.0
                    while client.is_connected:
                        await self.read_once(client)
                        await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # BLE errors are many and varied; log and retry
                log.warning("%s: %s", self.state.name, e)
                self.state.error = str(e) or type(e).__name__
            self.state.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
