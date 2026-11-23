# Shared Bluetooth LE scanner (`boatdash/ble.py`)

BlueZ allows one discovery session per adapter. `BleakClient("MAC")` starts its own discovery to
resolve the address, so it fails with `org.bluez.Error.InProgress` while any scanner runs. This
was observed when Victron listening and JBD connections ran together.

Rule: **the app has exactly one scanner — `BleHub`.** Nothing else may create a `BleakScanner` or
connect by address.

- Listeners (`hub.add_listener`) receive `(MAC, manufacturer_data)` for every advertisement.
  A failing listener is logged and doesn't affect others.
- The hub caches the latest `BLEDevice` per MAC. Connecting clients call
  `await hub.wait_for_device(mac)` (wrapped in `asyncio.timeout`) and pass the device object to
  `BleakClient`, which then connects without a second discovery.
- Watchdog: if no advertisement arrives for 60 s the scanner is restarted (BlueZ can go silent).
- Scanner errors restart with exponential backoff 2 → 60 s.

Verified live on navcentral: 2 JBD batteries connected + 3 Victron devices decoded, no errors.
