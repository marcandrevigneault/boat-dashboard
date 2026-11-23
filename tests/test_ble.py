"""Shared BLE hub: dispatch, device cache, waiting for a device (no adapter needed)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from boatdash.ble import BleHub


@dataclass
class FakeDevice:
    address: str


def test_dispatches_to_listeners_with_normalized_mac() -> None:
    hub = BleHub()
    got: list[tuple[str, dict[int, bytes]]] = []
    hub.add_listener(lambda mac, md: got.append((mac, md)))
    hub.on_advertisement(FakeDevice("aa:bb:cc:dd:ee:ff"), {0x02E1: b"\x10"})
    assert got == [("AA:BB:CC:DD:EE:FF", {0x02E1: b"\x10"})]


def test_failing_listener_does_not_block_others() -> None:
    hub = BleHub()
    got: list[str] = []

    def boom(_mac: str, _md: dict[int, bytes]) -> None:
        raise RuntimeError("bad listener")

    hub.add_listener(boom)
    hub.add_listener(lambda mac, _md: got.append(mac))
    hub.on_advertisement(FakeDevice("AA:00:00:00:00:01"), {})
    assert got == ["AA:00:00:00:00:01"]


def test_device_cache_keeps_latest() -> None:
    hub = BleHub()
    first, second = FakeDevice("AA:00:00:00:00:01"), FakeDevice("AA:00:00:00:00:01")
    hub.on_advertisement(first, {})
    hub.on_advertisement(second, {})
    assert hub.device("aa:00:00:00:00:01") is second
    assert hub.device("AA:00:00:00:00:02") is None


async def test_wait_for_device_returns_immediately_when_known() -> None:
    hub = BleHub()
    dev = FakeDevice("AA:00:00:00:00:01")
    hub.on_advertisement(dev, {})
    assert await hub.wait_for_device("aa:00:00:00:00:01") is dev


async def test_wait_for_device_resolves_when_seen_later() -> None:
    hub = BleHub()
    dev = FakeDevice("AA:00:00:00:00:01")
    waiter = asyncio.create_task(hub.wait_for_device("AA:00:00:00:00:01"))
    await asyncio.sleep(0)
    assert not waiter.done()
    hub.on_advertisement(dev, {})
    assert await asyncio.wait_for(waiter, 1) is dev


async def test_wait_for_device_honours_caller_timeout() -> None:
    hub = BleHub()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await hub.wait_for_device("AA:00:00:00:00:09")
