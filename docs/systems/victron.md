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

## Control
Not possible over instant readout. SmartSolar on/off is planned via VE.Direct (board PWR-4).

## Testing
`tests/test_victron.py` builds encrypted frames with a fake key (bit-packed exactly like the
devices) and checks decoded values for all three device types, plus wrong key, unknown device,
malformed frames and duplicate suppression.
