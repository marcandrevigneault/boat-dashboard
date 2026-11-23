"""VE.Smart session and solar on/off control against a simulated SmartSolar (no adapter needed).

The fake device implements the transport the way the real one behaved on our 150/45
(see docs/systems/victron.md): credit 1 chunk at a time, CBOR messages, instance tree
0 → 1 → 3, register echo on write, VALUE_RESPONSE on refusal.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import cbor2
import pytest

from boatdash import vesmart
from boatdash.vesmart import (
    CONTROL,
    DATA,
    LAST_DATA,
    Params,
    Session,
    VeSmartError,
    deepest_instance,
    encode,
    parse_chunk,
    pieces,
)
from boatdash.victron_control import Busy, ChargerControl, load_pins

PARAMS = bytes.fromhex("00040001de4a00")  # what our SmartSolar returned


class FakeDevice:
    """Speaks VE.Smart over an in-memory link."""

    def __init__(self, mode: int = 1, remote: int = 2, refuse: bool = False) -> None:
        self.regs = {(3, 0x0200): bytes([mode]), (3, 0x0202): remote.to_bytes(4, "little")}
        self.refuse = refuse  # answer writes with VALUE_RESPONSE 3
        self.ignore_writes = False  # echo the old value (write silently not applied)
        self.notify: dict[str, Callable[[bytes], None]] = {}
        self.rx = b""
        self.opened = False
        self.writes: list[tuple[str, bytes]] = []
        self.chunk_size = 0xDE

    # Link protocol
    async def read(self, uuid: str) -> bytes:
        assert uuid == CONTROL
        return PARAMS

    async def start_notify(self, uuid: str, callback: Callable[[bytes], None]) -> None:
        self.notify[uuid] = callback

    async def write(self, uuid: str, data: bytes) -> None:
        self.writes.append((uuid, data))
        if uuid == CONTROL:
            if data == vesmart.OPEN:
                self.opened = True
                self._later(CONTROL, b"\xf9\x01")
            return
        assert self.opened, "wrote data before opening the transport"
        if uuid == DATA:
            self.rx += data
            return
        chunk, self.rx = self.rx + data, b""
        assert len(chunk) <= self.chunk_size
        self._later(CONTROL, b"\xf9\x01")
        self._handle(chunk)

    def _later(self, uuid: str, data: bytes) -> None:
        asyncio.get_running_loop().call_soon(self.notify[uuid], data)

    def _reply(self, *items: object) -> None:
        msg = encode(*items)
        for uuid, part in pieces(msg, 0x4A):
            self._later(uuid, part)

    def _handle(self, chunk: bytes) -> None:
        import io

        stream = io.BytesIO(chunk)
        dec = cbor2.CBORDecoder(stream)
        while stream.tell() < len(chunk):
            op = dec.decode()
            if op == vesmart.GET_DEVICES:
                self._reply(vesmart.DEVICE_LIST, [0, 0, 1, 0, 3, 1])
            elif op == vesmart.SUBSCRIBE:
                self._reply(vesmart.RESPONSE, dec.decode(), 3, 0)
            elif op == vesmart.GET_VALUES:
                inst, vregs = dec.decode(), dec.decode()
                for v in vregs:
                    if (inst, v) in self.regs:
                        self._reply(vesmart.VALUE, inst, v, self.regs[(inst, v)])
                    else:
                        self._reply(vesmart.VALUE_RESPONSE, inst, v, 1)
            elif op == vesmart.SET_VALUES:
                inst, (vreg, raw) = dec.decode(), dec.decode()
                if self.refuse:
                    self._reply(vesmart.VALUE_RESPONSE, inst, vreg, 3)
                    continue
                if not self.ignore_writes:
                    self.regs[(inst, vreg)] = bytes(raw)
                self._reply(vesmart.VALUE, inst, vreg, self.regs[(inst, vreg)])


def connector(device: FakeDevice, fail_times: int = 0) -> Callable[..., object]:
    calls = {"n": 0}

    @asynccontextmanager
    async def connect(_address: str, _pin: str) -> AsyncIterator[FakeDevice]:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise OSError("le-connection-abort-by-local")
        yield device

    return connect


# ---- encoding ---------------------------------------------------------------------------------
def test_messages_match_captured_bytes() -> None:
    assert vesmart.set_value(3, 0x0200, b"\x04") == bytes.fromhex("0603821902004104")
    assert vesmart.get_values(3, [0x0100, 0x0102]) == bytes.fromhex("050382190100190102")


def test_params_parse_and_minimum_att_length() -> None:
    p = Params.parse(PARAMS)
    assert (p.max_free_chunks, p.chunk_size, p.max_att_length) == (1, 0xDE, 0x4A)
    assert Params.parse(bytes.fromhex("0004000140")).max_att_length == 20
    with pytest.raises(VeSmartError):
        Params.parse(b"\x00")


def test_pieces_put_last_part_on_last_data() -> None:
    parts = pieces(bytes(50), 20)
    assert [u for u, _ in parts] == [DATA, DATA, LAST_DATA]
    assert b"".join(p for _, p in parts) == bytes(50)


def test_parse_chunk_stops_at_unknown_opcode_and_garbage() -> None:
    chunk = encode(vesmart.VALUE, 3, 0x0200, b"\x01") + encode(99, 1) + encode(8, 3, 1, b"x")
    assert [m.op for m in parse_chunk(chunk)] == [vesmart.VALUE]
    assert parse_chunk(b"\xff\xff") == []


def test_deepest_instance() -> None:
    assert deepest_instance([(0, 0), (1, 0), (3, 1)]) == 3
    assert deepest_instance([]) == 0


# ---- session ----------------------------------------------------------------------------------
async def open_session(dev: FakeDevice) -> tuple[Session, int]:
    s = Session(dev, timeout=1)
    await s.open()
    return s, deepest_instance(await s.devices())


async def test_session_reads_and_writes_with_read_back() -> None:
    dev = FakeDevice(mode=1)
    s, inst = await open_session(dev)
    assert inst == 3
    assert await s.read(3, 0x0200) == b"\x01"
    await s.write(3, 0x0200, b"\x04")
    assert dev.regs[(3, 0x0200)] == b"\x04"


async def test_session_refused_write_raises() -> None:
    s, _ = await open_session(FakeDevice(refuse=True))
    with pytest.raises(VeSmartError, match="access denied"):
        await s.write(3, 0x0200, b"\x04")


async def test_session_write_not_applied_is_detected() -> None:
    dev = FakeDevice(mode=1)
    s, _ = await open_session(dev)
    dev.ignore_writes = True
    with pytest.raises(VeSmartError, match="reads 01 after writing 04"):
        await s.write(3, 0x0200, b"\x04")


async def test_session_unknown_register() -> None:
    s, _ = await open_session(FakeDevice())
    with pytest.raises(VeSmartError, match="unknown register"):
        await s.read(3, 0x1234)


async def test_session_waits_for_credit_and_times_out() -> None:
    dev = FakeDevice()
    s = Session(dev, timeout=0.05)
    with pytest.raises(VeSmartError, match="not open"):
        await s.send(b"\x01")
    await s.open()
    await asyncio.sleep(0)  # the device's first F9 01
    s._free = 0
    with pytest.raises(VeSmartError, match="flow control"):
        await s.send(encode(vesmart.GET_DEVICES))


async def test_session_gives_credit_back_once() -> None:
    dev = FakeDevice()
    s, _ = await open_session(dev)
    for _ in range(vesmart.GRANT_AFTER + 1):
        s._on_last(encode(vesmart.RESPONSE, 3, 3, 0))
    await asyncio.sleep(0)
    grants = [d for u, d in dev.writes if u == CONTROL and d[0] == 0xF9]
    assert grants == [bytes([0xF9, 0x80]), bytes([0xF9, vesmart.GRANT_AFTER + 1])]


# ---- controller -------------------------------------------------------------------------------
async def test_control_switches_off_and_on() -> None:
    dev = FakeDevice(mode=1)
    c = ChargerControl("SmartSolar", "e3:e4:87:f8:eb:a1", "000000", connector(dev))  # type: ignore[arg-type]
    assert await c.refresh() == "on"
    assert await c.set_mode(False) == "off"
    assert dev.regs[(3, 0x0200)] == b"\x04"
    assert c.state.mode == "off" and c.state.error is None and c.state.checked
    assert await c.set_mode(True) == "on"
    assert c.address == "E3:E4:87:F8:EB:A1"


async def test_control_refuses_when_remote_control_disabled() -> None:
    dev = FakeDevice(mode=1, remote=0)
    c = ChargerControl("S", "AA", "0", connector(dev))  # type: ignore[arg-type]
    with pytest.raises(VeSmartError, match="remote on/off"):
        await c.set_mode(False)
    assert dev.regs[(3, 0x0200)] == b"\x01"  # untouched
    assert c.state.error == "refused" and not c.state.busy


async def test_control_retries_flaky_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    c = ChargerControl("S", "AA", "0", connector(FakeDevice(mode=4), fail_times=2))  # type: ignore[arg-type]
    assert await c.refresh() == "off"


async def test_control_gives_up_after_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    c = ChargerControl("S", "AA", "0", connector(FakeDevice(), fail_times=9))  # type: ignore[arg-type]
    with pytest.raises(ConnectionError):
        await c.refresh()
    assert c.state.error == "unreachable" and c.state.mode is None


async def test_control_rejects_concurrent_commands() -> None:
    gate = asyncio.Event()

    @asynccontextmanager
    async def slow(_a: str, _p: str) -> AsyncIterator[FakeDevice]:
        await gate.wait()
        yield FakeDevice()

    c = ChargerControl("S", "AA", "0", slow)  # type: ignore[arg-type]
    first = asyncio.create_task(c.set_mode(False))
    await asyncio.sleep(0)
    assert c.state.busy
    with pytest.raises(Busy):
        await c.set_mode(True)
    gate.set()
    assert await first == "off"


async def _no_sleep(_s: float) -> None:
    return None


def test_load_pins(tmp_path: Path) -> None:
    f = tmp_path / "pins.json"
    f.write_text('{"e3:e4:87:f8:eb:a1": "000000"}')
    assert load_pins(f) == {"E3:E4:87:F8:EB:A1": "000000"}
    assert load_pins(tmp_path / "missing.json") == {}
