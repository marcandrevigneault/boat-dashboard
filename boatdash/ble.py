"""Shared Bluetooth LE scanner.

BlueZ allows a single discovery session per adapter. If one component scans while another calls
`BleakClient(address)` (which starts its own discovery to resolve the address), the second fails
with `org.bluez.Error.InProgress`. So the app runs exactly one scanner, here, and:

- dispatches every advertisement to registered listeners (e.g. Victron instant readout), and
- remembers the latest `BLEDevice` per address, so connecting clients (e.g. JBD BMS) can call
  `BleakClient(device)` directly, with no extra discovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[int, bytes]], None]

WATCHDOG_S = 60.0  # restart the scanner if no advertisement at all arrives for this long


class BleHub:
    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._devices: dict[str, Any] = {}  # MAC → bleak BLEDevice (bounded by devices in range)
        self._seen: dict[str, asyncio.Event] = {}
        self._last_adv = time.monotonic()

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def on_advertisement(self, device: Any, manufacturer_data: dict[int, bytes]) -> None:
        mac = str(device.address).upper()
        self._last_adv = time.monotonic()
        self._devices[mac] = device
        if (ev := self._seen.get(mac)) is not None:
            ev.set()
        for listener in self._listeners:
            try:
                listener(mac, manufacturer_data)
            except Exception:  # one bad listener must not stop the others
                log.exception("BLE listener failed for %s", mac)

    def device(self, address: str) -> Any | None:
        return self._devices.get(address.upper())

    async def wait_for_device(self, address: str) -> Any:
        """Return the BLEDevice once the scanner has seen it. The caller sets the timeout."""
        mac = address.upper()
        if (dev := self._devices.get(mac)) is not None:
            return dev
        ev = self._seen.setdefault(mac, asyncio.Event())
        await ev.wait()
        return self._devices[mac]

    async def run(self) -> None:  # pragma: no cover - needs a Bluetooth adapter
        from bleak import BleakScanner

        def cb(device: Any, adv: Any) -> None:
            self.on_advertisement(device, {k: bytes(v) for k, v in adv.manufacturer_data.items()})

        backoff = 2.0
        while True:
            try:
                async with BleakScanner(cb):
                    backoff = 2.0
                    self._last_adv = time.monotonic()
                    # periodic watchdog check, not waiting on an event
                    while time.monotonic() - self._last_adv < WATCHDOG_S:  # noqa: ASYNC110
                        await asyncio.sleep(WATCHDOG_S / 4)
                    log.warning("no BLE advertisements for %ss, restarting scanner", WATCHDOG_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("BLE scanner stopped: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
