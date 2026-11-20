"""Unit tests for the JBD BMS protocol (no Bluetooth hardware needed)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from boatdash.jbd import (
    CMD_BASIC_INFO,
    CMD_CELL_VOLTAGES,
    BatteryState,
    JBDClient,
    build_read_request,
    parse_basic_info,
    parse_cell_voltages,
    verify_frame,
)


def make_frame(register: int, payload: bytes, status: int = 0x00) -> bytes:
    checksum = (0x10000 - (len(payload) + sum(payload))) & 0xFFFF
    return (
        bytes([0xDD, register, status, len(payload), *payload])
        + checksum.to_bytes(2, "big")
        + b"\x77"
    )


def basic_info_payload(
    *,
    voltage_cv: int = 1308,
    current_ca: int = -327,
    remaining_cah: int = 19248,
    nominal_cah: int = 28000,
    cycles: int = 2,
    protection: int = 0,
    soc: int = 69,
    fet: int = 0b11,
    temps_dk: tuple[int, ...] = (2777,),
) -> bytes:
    p = bytearray()
    p += voltage_cv.to_bytes(2, "big")
    p += current_ca.to_bytes(2, "big", signed=True)
    p += remaining_cah.to_bytes(2, "big")
    p += nominal_cah.to_bytes(2, "big")
    p += cycles.to_bytes(2, "big")
    p += (0).to_bytes(2, "big")  # production date
    p += (0).to_bytes(4, "big")  # balance status low/high
    p += protection.to_bytes(2, "big")
    p += bytes([0x10, soc, fet, 4, len(temps_dk)])  # version, RSOC, FET, cells, NTCs
    for t in temps_dk:
        p += t.to_bytes(2, "big")
    return bytes(p)


def state() -> BatteryState:
    return BatteryState(name="Test", address="00:00:00:00:00:00")


class TestRequest:
    def test_basic_info_request_matches_known_bytes(self) -> None:
        assert build_read_request(CMD_BASIC_INFO).hex() == "dda50300fffd77"

    def test_cell_voltage_request_matches_known_bytes(self) -> None:
        assert build_read_request(CMD_CELL_VOLTAGES).hex() == "dda50400fffc77"


class TestVerifyFrame:
    def test_returns_payload(self) -> None:
        assert verify_frame(make_frame(3, b"\x01\x02")) == b"\x01\x02"

    def test_rejects_bad_checksum(self) -> None:
        frame = bytearray(make_frame(3, b"\x01\x02"))
        frame[-2] ^= 0xFF
        with pytest.raises(ValueError, match="checksum"):
            verify_frame(bytes(frame))

    def test_rejects_error_status(self) -> None:
        with pytest.raises(ValueError, match="error status"):
            verify_frame(make_frame(3, b"", status=0x80))

    @pytest.mark.parametrize(
        "frame", [b"", b"\xdd\x03", b"\x00" * 7, b"\xdd\x03\x00\x05\x01\x00\x00\x77"]
    )
    def test_rejects_malformed(self, frame: bytes) -> None:
        with pytest.raises(ValueError):
            verify_frame(frame)


class TestParsers:
    def test_basic_info_matches_real_battery_reading(self) -> None:
        s = state()
        parse_basic_info(basic_info_payload(), s)
        assert s.voltage == 13.08
        assert s.current == -3.27
        assert s.power == -42.8
        assert s.remaining_ah == 192.48
        assert s.capacity_ah == 280.0
        assert s.soc == 69
        assert s.cycles == 2
        assert s.temperatures == [4.6]
        assert s.charge_enabled and s.discharge_enabled
        assert s.protections == []

    def test_protection_flags_and_fet_state(self) -> None:
        s = state()
        parse_basic_info(basic_info_payload(protection=0b10_0000_0010, fet=0b01), s)
        assert s.protections == ["cell_undervoltage", "discharge_overcurrent"]
        assert s.charge_enabled is True
        assert s.discharge_enabled is False

    def test_cell_voltages(self) -> None:
        s = state()
        parse_cell_voltages(bytes.fromhex("0cc70cc70cc70cc6"), s)
        assert s.cells == [3.271, 3.271, 3.271, 3.270]
        d = s.to_dict()
        assert d["cell_delta_mv"] == 1
        assert d["cell_min"] == 3.270


class FakeClient:
    """Stands in for BleakClient: answers each write with a notification, split in chunks."""

    def __init__(self, bms: JBDClient, responses: dict[int, bytes], chunk: int = 20) -> None:
        self.bms, self.responses, self.chunk = bms, responses, chunk

    async def write_gatt_char(self, _uuid: str, data: bytes, response: bool = False) -> None:
        frame = self.responses[data[2]]
        loop = asyncio.get_running_loop()
        for i in range(0, len(frame), self.chunk):
            loop.call_soon(self.bms._on_notify, None, bytearray(frame[i : i + self.chunk]))


async def test_read_once_reassembles_chunked_notifications() -> None:
    bms = JBDClient("Test", "00:00:00:00:00:00")
    client: Any = FakeClient(
        bms,
        {
            CMD_BASIC_INFO: make_frame(CMD_BASIC_INFO, basic_info_payload()),
            CMD_CELL_VOLTAGES: make_frame(CMD_CELL_VOLTAGES, bytes.fromhex("0cc70cc70cc70cc6")),
        },
        chunk=7,
    )
    await bms.read_once(client)
    assert bms.state.soc == 69
    assert bms.state.cells == [3.271, 3.271, 3.271, 3.270]
    assert bms.state.updated is not None
    assert bms.state.error is None
