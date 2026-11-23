"""VE.Smart: the protocol VictronConnect speaks to Victron devices over a paired GATT link.

Victron does not document it. This follows the reverse-engineering notes of pysmartsolar
(MIT, trackIT Systems, docs/gatt-protocol.md) and was verified on our SmartSolar MPPT 150/45
(firmware 1.74). See docs/systems/victron.md.

Transport: three characteristics. Both sides send *chunks* (one or more CBOR messages) in pieces
of at most ``max_att_length`` bytes: all pieces but the last on DATA, the last on LAST_DATA.
Flow control by credit on CONTROL: ``F9 n`` lets the other side send ``n`` more chunks. The
SmartSolar allows one chunk at a time, so each chunk waits for the previous one's ``F9 01``.

Messages: an opcode followed by its CBOR arguments. Register values are byte strings in the
little-endian encoding of Victron's VE.Direct HEX protocol (same register numbers).
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import cbor2

log = logging.getLogger(__name__)

SERVICE = "306b0001-b081-4037-83dc-e59fcc3cdfd0"
CONTROL = "306b0002-b081-4037-83dc-e59fcc3cdfd0"
LAST_DATA = "306b0003-b081-4037-83dc-e59fcc3cdfd0"
DATA = "306b0004-b081-4037-83dc-e59fcc3cdfd0"

# Opcodes
GET_DEVICES, DEVICE_LIST, SUBSCRIBE = 1, 2, 3
GET_VALUES, SET_VALUES, RESPONSE, VALUE, VALUE_RESPONSE = 5, 6, 7, 8, 9
# Arguments the device sends after each opcode (instance first, except DEVICE_LIST)
_DEVICE_ARGS = {DEVICE_LIST: 1, RESPONSE: 3, VALUE: 3, VALUE_RESPONSE: 3}

CTL_ERROR, CTL_RESET, CTL_READY = 0xF7, 0xF8, 0xF9
OPEN = bytes([0xFA, 0x80, 0xFF])  # written once after reading the parameters (constant)
INITIAL_GRANT = 0x80  # chunks we let the device send at first
GRANT_AFTER = 0x40  # give chunks back once more than this many arrived (device keeps a u8)

RESULTS = {1: "unknown register", 3: "access denied", -5: "index out of range"}


class VeSmartError(Exception):
    """The device refused, did not answer, or the link was lost."""


class Link(Protocol):
    """The GATT operations the session needs (bleak in production, a fake in tests)."""

    async def read(self, uuid: str) -> bytes: ...

    async def write(self, uuid: str, data: bytes) -> None: ...

    async def start_notify(self, uuid: str, callback: Callable[[bytes], None]) -> None: ...


@dataclass(frozen=True)
class Params:
    flags: int
    max_instances: int
    max_free_chunks: int
    chunk_size: int
    max_att_length: int

    @classmethod
    def parse(cls, data: bytes) -> Params:
        """``flags u8, max_instances u16, max_free_chunks u8, chunk_size u8 [, max_att u16]``."""
        if len(data) < 5:
            raise VeSmartError(f"bad transport parameters {data.hex() or '(empty)'}")
        att = int.from_bytes(data[5:7], "little") if len(data) >= 7 else 0
        return cls(data[0], int.from_bytes(data[1:3], "little"), data[3], data[4], max(att, 20))


def encode(*items: Any) -> bytes:
    return b"".join(cbor2.dumps(i) for i in items)


def get_values(instance: int, vregs: list[int]) -> bytes:
    return encode(GET_VALUES, instance, vregs)


def set_value(instance: int, vreg: int, raw: bytes) -> bytes:
    """``06 03 82 19 0200 41 04`` sets register 0x0200 of instance 3 to 4."""
    return encode(SET_VALUES, instance, [vreg, raw])


@dataclass(frozen=True)
class Message:
    op: int
    args: tuple[Any, ...]


def parse_chunk(chunk: bytes) -> list[Message]:
    """Messages in one received chunk. An unknown opcode ends it (its length is unknown)."""
    stream = io.BytesIO(chunk)
    decoder = cbor2.CBORDecoder(stream)
    out: list[Message] = []
    while stream.tell() < len(chunk):
        try:
            op = decoder.decode()
            count = _DEVICE_ARGS.get(op) if isinstance(op, int) else None
            if count is None:
                break
            out.append(Message(op, tuple(decoder.decode() for _ in range(count))))
        except (cbor2.CBORDecodeError, EOFError):
            log.debug("undecodable VE.Smart chunk %s", chunk.hex())
            break
    return out


def pieces(chunk: bytes, max_att: int) -> list[tuple[str, bytes]]:
    parts = [chunk[i : i + max_att] for i in range(0, len(chunk), max_att)]
    return [(LAST_DATA if i == len(parts) - 1 else DATA, p) for i, p in enumerate(parts)]


class Session:
    """One open VE.Smart session on a connected, paired link."""

    def __init__(self, link: Link, timeout: float = 5.0) -> None:
        self.link = link
        self.timeout = timeout
        self.params: Params | None = None
        self._free = 0
        self._credit = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._rx = b""
        self._received = 0
        self._devices: asyncio.Future[list[tuple[int, int]]] | None = None
        # (instance, vreg) → futures waiting for that register's next VALUE (or a refusal)
        self._waiters: dict[tuple[int, int], list[asyncio.Future[bytes]]] = {}
        self._background: set[asyncio.Task[None]] = set()

    # ---- transport -------------------------------------------------------------------------
    async def open(self) -> None:
        await self.link.start_notify(CONTROL, self._on_control)
        await self.link.start_notify(LAST_DATA, self._on_last)
        await self.link.start_notify(DATA, self._on_data)
        self.params = Params.parse(await self.link.read(CONTROL))
        await self.link.write(CONTROL, OPEN)
        await self.link.write(CONTROL, bytes([CTL_READY, INITIAL_GRANT]))

    async def send(self, message: bytes) -> None:
        if self.params is None:
            raise VeSmartError("session not open")
        if len(message) > self.params.chunk_size:
            raise VeSmartError("message larger than one chunk")
        async with self._send_lock:
            while self._free <= 0:
                self._credit.clear()
                try:
                    async with asyncio.timeout(self.timeout):
                        await self._credit.wait()
                except TimeoutError:
                    raise VeSmartError("device allowed no chunk (flow control)") from None
            self._free -= 1
            for uuid, part in pieces(message, self.params.max_att_length):
                await self.link.write(uuid, part)

    def _on_control(self, data: bytes) -> None:
        if len(data) >= 2 and data[0] == CTL_READY:
            limit = max(1, self.params.max_free_chunks) if self.params else 0xFF
            self._free = min(self._free + data[1], limit)
            self._credit.set()
        elif data[:1] == bytes([CTL_RESET]):
            self._rx = b""
        elif data[:1] == bytes([CTL_ERROR]):
            log.info("VE.Smart device error %s", data[1:].hex())
        # anything else: the parameters echoed as a notification

    def _on_data(self, data: bytes) -> None:
        self._rx += data

    def _on_last(self, data: bytes) -> None:
        chunk, self._rx = self._rx + data, b""
        self._received += 1
        if self._received > GRANT_AFTER:
            count, self._received = self._received, 0  # counted here: never give back twice
            task = asyncio.get_running_loop().create_task(
                self.link.write(CONTROL, bytes([CTL_READY, count]))
            )
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        for message in parse_chunk(chunk):
            self._dispatch(message)

    # ---- messages --------------------------------------------------------------------------
    def _dispatch(self, m: Message) -> None:
        if m.op == DEVICE_LIST:
            flat = m.args[0] if isinstance(m.args[0], list) else []
            devices = [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]
            if self._devices is not None and not self._devices.done():
                self._devices.set_result(devices)
        elif m.op == VALUE:
            instance, vreg, raw = m.args
            for fut in self._waiters.pop((instance, vreg), []):
                if not fut.done():
                    fut.set_result(bytes(raw))
        elif m.op == VALUE_RESPONSE:
            instance, vreg, code = m.args
            reason = RESULTS.get(code, f"code {code}")
            for fut in self._waiters.pop((instance, vreg), []):
                if not fut.done():
                    fut.set_exception(VeSmartError(f"register 0x{vreg:04x}: {reason}"))

    async def _await(self, fut: asyncio.Future[Any], what: str) -> Any:
        try:
            async with asyncio.timeout(self.timeout):
                return await fut
        except TimeoutError:
            raise VeSmartError(f"no answer for {what}") from None

    async def devices(self) -> list[tuple[int, int]]:
        """[(instance, parent), ...]; also subscribes to each (the device needs it to answer)."""
        self._devices = asyncio.get_running_loop().create_future()
        await self.send(encode(GET_DEVICES))
        devices: list[tuple[int, int]] = await self._await(self._devices, "device list")
        for instance, _ in devices:
            await self.send(encode(SUBSCRIBE, instance))
        return devices

    def _expect(self, instance: int, vreg: int) -> asyncio.Future[bytes]:
        fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._waiters.setdefault((instance, vreg), []).append(fut)
        return fut

    async def read(self, instance: int, vreg: int) -> bytes:
        fut = self._expect(instance, vreg)
        await self.send(get_values(instance, [vreg]))
        raw: bytes = await self._await(fut, f"register 0x{vreg:04x}")
        return raw

    async def write(self, instance: int, vreg: int, raw: bytes) -> None:
        """Write, then confirm with a fresh read: settings are only trusted once read back."""
        fut = self._expect(instance, vreg)
        await self.send(set_value(instance, vreg, raw))
        await self._await(fut, f"write of 0x{vreg:04x}")  # echo (or refusal)
        back = await self.read(instance, vreg)
        if back != raw:  # a periodic push sent before the write may arrive late: ask once more
            await asyncio.sleep(0.5)
            back = await self.read(instance, vreg)
        if back != raw:
            raise VeSmartError(
                f"register 0x{vreg:04x} reads {back.hex()} after writing {raw.hex()}"
            )


def deepest_instance(devices: list[tuple[int, int]]) -> int:
    """The charger is the deepest instance of the tree (SmartSolar: 0 BT → 1 UART → 3 charger)."""
    parents = dict(devices)

    def depth(instance: int) -> int:
        n = 0
        while parents.get(instance, instance) != instance and n < len(parents):
            instance, n = parents[instance], n + 1
        return n

    return max((i for i, _ in devices), key=depth, default=0)
