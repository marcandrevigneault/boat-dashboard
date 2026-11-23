# Board

Kanban for the technical team. Move items between columns in the PR that does the work.
IDs: CORE (backend platform), UI, PWR (power), NAV (navigation), N2K (NMEA 2000), CHART, RADAR,
WX (weather/routing), OPS (hardware/deploy).

## In progress
- **CORE-0 Engineering foundation** — PR #1 (`chore/engineering-foundation`), CI green.
  Next step: owner merges PR #1 (merge policy still to be decided by owner), then start CORE-1.

- **PWR-1 Victron monitoring over BLE** — branch `feat/victron-ble`. Decode "instant readout"
  advertisements (library `victron-ble`) for SmartSolar MPPT (E3:E4:87:F8:EB:A1), SmartBMV
  (D1:E9:74:07:83:07) and Orion XS DC-DC (FB:AF:0B:1F:75:FB); add cards to the dashboard.
  Status: devices found; Orion XS broadcasts instant readout, SmartSolar + BMV appear to have it off.
  Blocked on owner: enable instant readout on SmartSolar + BMV and provide the 3 encryption keys
  (stored in `~/.config/boatdash/victron-keys.json`, never in the repo). Next step: decoder +
  tests + cards.

## Next
- **PWR-4 SmartSolar ON/OFF control** — BLE instant readout is read-only, so control goes through the
  documented VE.Direct HEX protocol (device mode register 0x0200: on/off) over a VE.Direct-to-USB
  cable. Blocked on owner: buy the cable. UI: ON/OFF button with confirmation and live state.
- **NAV-1 GPS position, speed, course** — read gpsd (u-blox 7 on USB, 3D fix confirmed); show in UI.
  Depends on CORE-1.
- **CORE-1 Data store + WebSocket deltas** — Signal K paths/SI units, app factory, typed config
  (pydantic), snapshot on connect then changed paths only. Raise coverage gate to 85 %.
- **UI-1 Design system + app shell** — choose frontend stack (ADR), design tokens (type, spacing,
  colour), day/night/red modes, navigation between pages, battery page rebuilt on it.
  Aesthetics review with screenshots at phone/tablet/desktop widths.
- **OPS-1 Branch protection** — require CI on `main`.
- **CORE-2 E2E suite + test tiers in CI** — browser E2E (Playwright) against a simulated backend
  (fake BMS/GPS sources); CI job skipped when the PR has the `light-tests` label, always run on `main`.

## Backlog
- **PWR-2 History** — store battery/GPS history efficiently (ring buffer + downsampled on-disk
  store), charts of SOC/current over 24 h/7 d.
- **PWR-3 Alarms** — thresholds (low SOC, cell imbalance, BMS protection), sound + visual.
- **N2K-1 NMEA 2000 interface** — CAN HAT on Pi (PiCAN-M or isolated Waveshare), SocketCAN,
  device list of everything on the SeaTalkNG backbone. Hardware not bought yet.
- **N2K-2 Instruments** — depth, wind, speed through water, heading, engine data from N2K.
- **CHART-1 Chart view** — MapLibre GL, own boat + track, offline tiles. Licensing note: CHS
  (Canadian) ENCs are paid; NOAA (US) are free; OpenSeaMap as free overlay.
- **RADAR-1 Radar overlay** — depends on radar model (Raymarine via RayNet Ethernet?). Ask owner.
- **WX-1 Weather routing** — GRIB download when online, isochrone routing with boat polars.
- **OPS-2 Raspberry Pi 5 migration** — image, NVMe boot, services, 12 V power, cooling, BLE range
  check from behind the panel.
- **OPS-3 Fixed address / `navcentral.local`** — mDNS so screens find the app without an IP.

## Done
- **PWR-0 JBD BMS over BLE** — both batteries live, reconnects, French UI, systemd service.
