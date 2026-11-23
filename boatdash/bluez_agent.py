# No `from __future__ import annotations`: dbus-fast reads the annotations as D-Bus signatures.
"""BlueZ pairing agent that answers passkey requests with a fixed PIN (Victron devices).

Must be registered *before* the connection opens: BlueZ may start pairing on its own while it
discovers the services of a device that requires it.
"""

import logging
from types import TracebackType
from typing import Any

from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method

log = logging.getLogger(__name__)

AGENT_PATH = "/boatdash/agent"


class _PasskeyAgent(ServiceInterface):
    def __init__(self, passkey: int) -> None:
        super().__init__("org.bluez.Agent1")
        self._passkey = passkey

    @method()
    def Release(self):  # type: ignore[no-untyped-def]
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # type: ignore[name-defined]  # noqa: F821
        return f"{self._passkey:06d}"

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # type: ignore[name-defined]  # noqa: F821
        log.info("answering BlueZ passkey request for %s", device)
        return self._passkey

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # type: ignore[name-defined,no-untyped-def]  # noqa: F821
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # type: ignore[name-defined,no-untyped-def]  # noqa: F821
        pass

    @method()
    def RequestAuthorization(self, device: "o"):  # type: ignore[name-defined,no-untyped-def]  # noqa: F821
        pass

    @method()
    def Cancel(self):  # type: ignore[no-untyped-def]
        pass


class PasskeyAgent:
    """``async with PasskeyAgent("123456"):`` — BlueZ uses our PIN while the block runs."""

    def __init__(self, pin: str) -> None:
        self._agent = _PasskeyAgent(int(pin))
        self._bus: MessageBus | None = None

    async def __aenter__(self) -> "PasskeyAgent":
        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._bus.export(AGENT_PATH, self._agent)
        manager = await self._manager()
        await manager.call_register_agent(AGENT_PATH, "KeyboardDisplay")
        await manager.call_request_default_agent(AGENT_PATH)
        return self

    async def _manager(self) -> Any:
        assert self._bus is not None
        intro = await self._bus.introspect("org.bluez", "/org/bluez")
        obj = self._bus.get_proxy_object("org.bluez", "/org/bluez", intro)
        return obj.get_interface("org.bluez.AgentManager1")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._bus is None:
            return
        try:
            await (await self._manager()).call_unregister_agent(AGENT_PATH)
        except Exception as error:
            log.debug("cannot unregister pairing agent: %r", error)
        finally:
            self._bus.disconnect()
            self._bus = None
