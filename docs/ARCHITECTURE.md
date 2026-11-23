# Architecture

## Goal
One app that shows and controls everything on board: power systems, NMEA 2000 (SeaTalkNG) devices,
GPS, charts, radar and weather routing — with a consumer-grade UI.

## Shape (target)

    Devices                      Backend (Python, asyncio)                  Clients (browser)
    ───────                      ─────────────────────────                  ─────────────────
    BLE BMS (JBD) ─────┐
    Victron (BLE adv) ─┤
    GPS (gpsd) ────────┼──► sources/* ──► Data store ──► WebSocket deltas ──► Web UI
    NMEA 2000 (CAN) ───┤      (one task     (latest value      + REST         (tablet, phone,
    Signal K server ───┘       per device)   per path, SI)                      display)

- **Sources** are independent asyncio tasks, one per device/protocol, that reconnect with backoff
  and never crash the app. Each writes normalized values into the store.
- **Data store** keeps the latest value per path using Signal K naming and SI units
  (e.g. `electrical.batteries.a.voltage`, `navigation.position`). Following Signal K lets us interoperate
  with a Signal K server later without remapping.
- **Transport**: clients receive a full snapshot on connect, then only changed paths (deltas),
  rate-limited. Keeps bandwidth and CPU low on the Pi and on tablets.
- **UI**: static web app served by the backend. Works offline (no internet at sea).

## Current state (v0.2)
- `boatdash/ble.py` — the single shared BLE scanner (see `docs/systems/ble.md`).
- `boatdash/jbd.py` — JBD BMS over BLE (see `docs/systems/bms-jbd.md`).
- `boatdash/victron.py` — Victron SmartSolar, BMV, Orion XS (see `docs/systems/victron.md`).
- `boatdash/server.py` — FastAPI app; pushes a full snapshot every second (to be replaced by the
  store + deltas, board item CORE-1).
- `web/index.html` — single page: energy flow, Victron cards, batteries (to be replaced by the design-system UI, UI-1).

## Decisions
See `docs/adr/`.
