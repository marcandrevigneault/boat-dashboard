"""Victron devices over Bluetooth LE "Instant readout".

Victron Smart devices broadcast their live values in BLE advertisements (manufacturer ID 0x02E1),
encrypted with AES-128-CTR using a per-device key shown in VictronConnect. We only listen: no
connection, no pairing, read-only. Advertisements come from the shared scanner (ble.py).

Decryption and bit-unpacking are done by the `victron-ble` library; this module maps the result to
our own stable, typed shape so the rest of the app doesn't depend on library internals.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from victron_ble.devices import BatteryMonitor, Device, OrionXS, SolarCharger
from victron_ble.exceptions import AdvertisementKeyMismatchError

log = logging.getLogger(__name__)

VICTRON_MANUFACTURER_ID = 0x02E1
INSTANT_READOUT_PREFIX = 0x10  # first byte of an "instant readout" advertisement

Kind = Literal["solar", "bmv", "orion"]

DECODERS: dict[str, type[Device]] = {
    "solar": SolarCharger,
    "bmv": BatteryMonitor,
    "orion": OrionXS,
}

DEFAULT_KEYS_FILE = Path.home() / ".config" / "boatdash" / "victron-keys.json"


def load_keys(path: Path | None = None) -> dict[str, str]:
    """Read {MAC: hex key} from the private keys file (never stored in the repo)."""
    path = path or Path(os.environ.get("BOATDASH_VICTRON_KEYS", DEFAULT_KEYS_FILE))
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        log.warning("no Victron keys file at %s", path)
        return {}
    return {str(mac).upper(): str(key).lower() for mac, key in raw.items()}


def _name(value: Any) -> str | None:
    """Enum → lowercase name ('bulk', 'no_error'); None stays None."""
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return value.name.lower() if value.name else str(value.value)
    return str(value)


def _get(data: Any, attr: str) -> Any:
    getter = getattr(data, f"get_{attr}", None)
    return getter() if getter else None


@dataclass
class VictronState:
    name: str
    address: str
    kind: Kind
    model: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    updated: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize(kind: Kind, data: Any) -> dict[str, Any]:
    """Map library output to our field names and units (V, A, W, Wh, Ah, %, min)."""
    if kind == "solar":
        v = _get(data, "battery_voltage")
        a = _get(data, "battery_charging_current")
        return {
            "state": _name(_get(data, "charge_state")),
            "error": _name(_get(data, "charger_error")),
            "pv_power": _get(data, "solar_power"),
            "battery_voltage": v,
            "battery_current": a,
            "charge_power": round(v * a, 1) if v is not None and a is not None else None,
            "yield_today_wh": _get(data, "yield_today"),
            "load_current": _get(data, "external_device_load"),
        }
    if kind == "bmv":
        v = _get(data, "voltage")
        a = _get(data, "current")
        soc = _get(data, "soc")
        return {
            "voltage": v,
            "current": a,
            "power": round(v * a, 1) if v is not None and a is not None else None,
            "soc": soc,
            "consumed_ah": _get(data, "consumed_ah"),
            "remaining_mins": _get(data, "remaining_mins"),
            "alarm": _name(_get(data, "alarm")),
            "aux_mode": _name(_get(data, "aux_mode")),
            "starter_voltage": _get(data, "starter_voltage"),
            "midpoint_voltage": _get(data, "midpoint_voltage"),
            "temperature": _get(data, "temperature"),
        }
    # orion
    vin, ain = _get(data, "input_voltage"), _get(data, "input_current")
    vout, aout = _get(data, "output_voltage"), _get(data, "output_current")
    return {
        "state": _name(_get(data, "charge_state")),
        "error": _name(_get(data, "charger_error")),
        "input_voltage": vin,
        "input_current": ain,
        "output_voltage": vout,
        "output_current": aout,
        "output_power": round(vout * aout, 1) if vout is not None and aout is not None else None,
        "off_reason": _name(_get(data, "off_reason")),
    }


class VictronMonitor:
    """Listens for Victron advertisements and keeps the latest decoded state per device."""

    def __init__(self, devices: list[tuple[str, str, Kind]], keys: dict[str, str]) -> None:
        self.states: dict[str, VictronState] = {}
        self._decoders: dict[str, Device] = {}
        self._last_raw: dict[str, bytes] = {}
        for name, address, kind in devices:
            mac = address.upper()
            self.states[mac] = VictronState(name=name, address=mac, kind=kind)
            if mac in keys:
                self._decoders[mac] = DECODERS[kind](keys[mac])
            else:
                self.states[mac].error = "missing_key"

    def handle(self, address: str, raw: bytes, now: float | None = None) -> bool:
        """Process one advertisement payload. Returns True if state changed."""
        mac = address.upper()
        state = self.states.get(mac)
        decoder = self._decoders.get(mac)
        if state is None or decoder is None or raw[:1] != bytes([INSTANT_READOUT_PREFIX]):
            return False
        if self._last_raw.get(mac) == raw:  # devices repeat identical frames; skip the AES work
            state.updated = now or time.time()
            return False
        self._last_raw[mac] = raw
        try:
            data = decoder.parse(raw)
        except AdvertisementKeyMismatchError:
            state.error = "wrong_key"
            return True
        except Exception as e:  # malformed or unsupported frame: keep last good values
            log.debug("%s: cannot decode %s: %s", state.name, raw.hex(), e)
            return False
        state.model = _get(data, "model_name")
        state.values = normalize(state.kind, data)
        state.updated = now or time.time()
        state.error = None
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.states.values()]

    def on_advertisement(self, address: str, manufacturer_data: dict[int, bytes]) -> None:
        """BleHub listener."""
        raw = manufacturer_data.get(VICTRON_MANUFACTURER_ID)
        if raw is not None:
            self.handle(address, raw)
