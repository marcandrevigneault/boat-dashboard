"""Victron instant-readout tests.

Frames are built here exactly as Victron devices build them (bit-packed LSB-first, AES-128-CTR with
the IV as little-endian counter, first ciphertext byte = key check), using a fake key. This tests
our code and the library together without real keys or hardware.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from boatdash.victron import VictronMonitor, load_keys

KEY = "00112233445566778899aabbccddeeff"
SOLAR = "AA:00:00:00:00:01"
BMV = "AA:00:00:00:00:02"
ORION = "AA:00:00:00:00:03"


class Bits:
    def __init__(self) -> None:
        self.value = 0
        self.n = 0

    def u(self, v: int, bits: int) -> Bits:
        self.value |= (v & ((1 << bits) - 1)) << self.n
        self.n += bits
        return self

    def s(self, v: int, bits: int) -> Bits:
        return self.u(v & ((1 << bits) - 1), bits)

    def bytes(self) -> bytes:
        return self.value.to_bytes((self.n + 7) // 8, "little")


def frame(model: int, readout: int, plain: bytes, iv: int = 0x1234, key: str = KEY) -> bytes:
    k = bytes.fromhex(key)
    ctr = Counter.new(128, initial_value=iv, little_endian=True)
    enc = AES.new(k, AES.MODE_CTR, counter=ctr).encrypt(plain)
    return (
        (0x0010).to_bytes(2, "little")
        + model.to_bytes(2, "little")
        + bytes([readout])
        + iv.to_bytes(2, "little")
        + bytes([k[0]])
        + enc
    )


def solar_frame(
    *, state: int = 3, pv_w: int = 245, v_cv: int = 1352, a_da: int = 181, iv: int = 1
) -> bytes:
    plain = (
        Bits()
        .u(state, 8)
        .u(0, 8)  # no error
        .s(v_cv, 16)
        .s(a_da, 16)
        .u(87, 16)  # yield today, 0.01 kWh → 870 Wh
        .u(pv_w, 16)
        .u(0x1FF, 9)  # load output not available
        .bytes()
    )
    return frame(0xA073, 0x01, plain, iv=iv)


def bmv_frame(*, soc_pm: int = 873, iv: int = 2) -> bytes:
    plain = (
        Bits()
        .u(612, 16)  # remaining minutes
        .s(1305, 16)  # 13.05 V
        .u(0, 16)  # no alarm
        .s(1256, 16)  # aux: starter 12.56 V
        .u(0, 2)  # aux mode: starter voltage
        .s(-11283, 22)  # -11.283 A
        .u(354, 20)  # consumed 35.4 Ah
        .u(soc_pm, 10)  # SOC in 0.1 %
        .bytes()
    )
    return frame(0xA381, 0x02, plain, iv=iv)


def orion_frame(iv: int = 3) -> bytes:
    plain = (
        Bits()
        .u(0, 8)  # off
        .u(0, 8)
        .u(1314, 16)  # out 13.14 V
        .u(0, 16)
        .u(1266, 16)  # in 12.66 V
        .u(0, 16)
        .u(0x08, 32)  # off reason: remote input
        .bytes()
    )
    return frame(0xA3F0, 0x0F, plain, iv=iv)


@pytest.fixture
def monitor() -> VictronMonitor:
    return VictronMonitor(
        [("Solaire", SOLAR, "solar"), ("BMV", BMV, "bmv"), ("Orion", ORION, "orion")],
        {SOLAR: KEY, BMV: KEY, ORION: KEY},
    )


def values(m: VictronMonitor, mac: str) -> dict[str, object]:
    return m.states[mac].values


def test_solar_charger(monitor: VictronMonitor) -> None:
    assert monitor.handle(SOLAR, solar_frame(), now=100.0)
    s = monitor.states[SOLAR]
    assert s.model == "SmartSolar Charger MPPT 150/45 rev3"
    assert s.updated == 100.0
    v = s.values
    assert v["state"] == "bulk"
    assert v["error"] == "no_error"
    assert v["pv_power"] == 245
    assert v["battery_voltage"] == 13.52
    assert v["battery_current"] == 18.1
    assert v["charge_power"] == 244.7
    assert v["yield_today_wh"] == 870
    assert v["load_current"] is None


def test_battery_monitor(monitor: VictronMonitor) -> None:
    assert monitor.handle(BMV, bmv_frame())
    v = values(monitor, BMV)
    assert v["voltage"] == 13.05
    assert v["current"] == -11.283
    assert v["power"] == -147.2
    assert v["soc"] == 87.3
    assert v["consumed_ah"] == -35.4
    assert v["remaining_mins"] == 612
    assert v["alarm"] == "no_alarm"
    assert v["aux_mode"] == "starter_voltage"
    assert v["starter_voltage"] == 12.56


def test_battery_monitor_unsynchronized_soc_is_none(monitor: VictronMonitor) -> None:
    monitor.handle(BMV, bmv_frame(soc_pm=0x3FF))
    assert values(monitor, BMV)["soc"] is None


def test_orion_xs(monitor: VictronMonitor) -> None:
    assert monitor.handle(ORION, orion_frame())
    v = values(monitor, ORION)
    assert v["state"] == "off"
    assert v["input_voltage"] == 12.66
    assert v["output_voltage"] == 13.14
    assert v["output_power"] == 0.0
    assert v["off_reason"] == "remote_input"


def test_identical_frame_skips_decode_but_refreshes_timestamp(monitor: VictronMonitor) -> None:
    raw = solar_frame()
    assert monitor.handle(SOLAR, raw, now=1.0)
    assert not monitor.handle(SOLAR, raw, now=2.0)
    assert monitor.states[SOLAR].updated == 2.0


def test_new_values_are_applied(monitor: VictronMonitor) -> None:
    monitor.handle(SOLAR, solar_frame(pv_w=100, iv=1))
    monitor.handle(SOLAR, solar_frame(pv_w=300, iv=2))
    assert values(monitor, SOLAR)["pv_power"] == 300


def test_wrong_key_is_reported_and_keeps_old_values(monitor: VictronMonitor) -> None:
    monitor.handle(SOLAR, solar_frame())
    bad = frame(0xA073, 0x01, b"\x00" * 12, key="ff" * 16)
    assert monitor.handle(SOLAR, bad)
    assert monitor.states[SOLAR].error == "wrong_key"
    assert values(monitor, SOLAR)["pv_power"] == 245


def test_ignores_unknown_devices_and_non_readout_frames(monitor: VictronMonitor) -> None:
    assert not monitor.handle("BB:BB:BB:BB:BB:BB", solar_frame())
    assert not monitor.handle(SOLAR, bytes.fromhex("01d21e76069cac76"))
    assert monitor.states[SOLAR].updated is None


def test_malformed_frame_does_not_raise(monitor: VictronMonitor) -> None:
    assert not monitor.handle(SOLAR, b"\x10\x00")


def test_missing_key_marks_device() -> None:
    m = VictronMonitor([("Solaire", SOLAR, "solar")], {})
    assert m.states[SOLAR].error == "missing_key"
    assert not m.handle(SOLAR, solar_frame())


def test_address_case_is_normalized() -> None:
    m = VictronMonitor([("Solaire", SOLAR.lower(), "solar")], {SOLAR: KEY})
    assert m.handle(SOLAR.lower(), solar_frame())


def test_snapshot_shape(monitor: VictronMonitor) -> None:
    monitor.handle(SOLAR, solar_frame())
    snap = {d["address"]: d for d in monitor.snapshot()}
    assert set(snap) == {SOLAR, BMV, ORION}
    assert snap[SOLAR]["kind"] == "solar"
    json.dumps(snap)  # must be JSON-serializable for the WebSocket


def test_load_keys(tmp_path: Path) -> None:
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"aa:00:00:00:00:01": "ABCDEF"}))
    assert load_keys(p) == {"AA:00:00:00:00:01": "abcdef"}
    assert load_keys(tmp_path / "missing.json") == {}
