# Victron devices (Bluetooth "Instant readout")

| Device | Role | MAC |
|---|---|---|
| SmartSolar MPPT 150/45 rev3 | Solar charge controller | E3:E4:87:F8:EB:A1 |
| BMV-712 Smart | Bank monitor (shunt); aux input = starter battery voltage | D1:E9:74:07:83:07 |
| Orion XS 12/12-50 | DC-DC charger, alternator → house bank; on/off by remote input (engine) | FB:AF:0B:1F:75:FB |

## How it works (`boatdash/victron.py`)
- Devices broadcast BLE advertisements, manufacturer ID `0x02E1`. Instant-readout frames start
  with `0x10`: `prefix(2) model(2, LE) readout_type(1) iv(2, LE) key_check(1) ciphertext`.
- Payload is AES-128-CTR, counter = IV little-endian, key from VictronConnect (Product info →
  Instant readout details). First ciphertext byte must equal key[0] (else `wrong_key`).
- Decrypt + bit-unpack (LSB-first fields) via the `victron-ble` library; `normalize()` maps its
  output to our field names/units so the rest of the app doesn't depend on library internals.
- Read-only: no connection or pairing. Advertisements come from the shared scanner (`ble.md`).
- Devices repeat identical frames; an identical frame only refreshes `updated` (no AES work).
- "Not available" sentinels become `null` (e.g. BMV SOC before its first sync after a reset).

## Keys
`~/.config/boatdash/victron-keys.json` (mode 600), `{ "MAC": "32-hex key" }`. Override path with
`BOATDASH_VICTRON_KEYS`. Never committed. A device without a key shows a "clé manquante" card.

## Control: solar charger on/off (`boatdash/vesmart.py`, `boatdash/victron_control.py`)
Instant readout is read-only, so control uses **VE.Smart**, the protocol VictronConnect speaks over
a *paired* GATT link. Victron does not document it; we follow pysmartsolar's reverse-engineering
notes (MIT) and verified it on our SmartSolar 150/45 (firmware 1.74) on 2026-11-23.

- Pairing: BlueZ agent (`bluez_agent.py`) answers the passkey with the device PIN from
  `~/.config/boatdash/victron-pins.json` (mode 600, `{ "MAC": "PIN" }`, never committed; override
  with `BOATDASH_VICTRON_PINS`). The bond persists in BlueZ. A device without a PIN gets no switch.
- Transport: service `306b0001-…`, characteristics control `…0002`, lastData `…0003`, data `…0004`.
  Read the parameters from control, write `FA 80 FF` and `F9 80`, then send CBOR messages in chunks,
  one at a time (wait for `F9 01` credit). GetDevices → `[0,0, 1,0, 3,1]`; Subscribe to each
  instance or the device does not answer reads. The charger is the deepest instance (3).
- Register `0x0200` device mode: `01` on, `04` off. Only honoured when `0x0202` bit 1 (remote
  on/off) is set — checked before writing. Every write waits for the echo, then **reads back**;
  the UI only shows a mode the charger confirmed.
- Each operation is one short session (connect, pair if needed, act, disconnect, ~4–5 s), so the
  phone app can still connect. Three attempts on link errors; refusals are not retried. One command
  at a time (HTTP 409 otherwise). The mode is also re-read at start-up and every 30 min (it can be
  changed from VictronConnect); each connect makes the charger's LEDs blink for a few seconds.
- API: `POST /api/victron/{name}/charger {"on": bool}` → `{"mode": "on"|"off"}` once confirmed;
  502 with `refused` / `unreachable`. The snapshot carries `control: {mode, busy, error, checked}`.
- Risk: undocumented protocol; a firmware update could change it. Failure mode is an error message,
  never an unknown state (we always read back). No authentication yet: anyone on the boat network
  can switch (board OPS-6).

## Testing
`tests/test_victron.py` builds encrypted frames with a fake key (bit-packed exactly like the
devices) and checks decoded values for all three device types, plus wrong key, unknown device,
malformed frames and duplicate suppression.
