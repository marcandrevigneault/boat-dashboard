# Board

Kanban for the technical team. Move items between columns in the PR that does the work.
IDs: CORE (backend platform), UI, PWR (power), NAV (navigation), N2K (NMEA 2000), CHART, RADAR,
WX (weather/routing), OPS (hardware/deploy).

## In progress
- **PWR-4 Solar charger ON/OFF** — PR open (`feat/solar-switch`), Full tier, verified live.
  Includes PRs #4 and #5 (merged in); merge those first, then this one.

## Next
- **OPS-5 Deploy from `main`** — the service runs from a separate checkout updated only from
  `main`, so switching branches in the dev checkout never changes what runs on board.
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
- **OPS-6 Access control** — today anyone on the boat Wi-Fi can use the controls (solar switch).
  Add a simple PIN/session for control actions before more controls land.
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

## Done
- **OPS-3 Name on the network** — open `http://navcentral:8080` (router DNS, search domain `lan`)
  or `http://navcentral.local:8080` (mDNS via avahi, works on any network). Server listens on IPv4
  and IPv6 (the router hands out IPv6 for the name; phones try it first).
- **CORE-0 Engineering foundation** — tooling, CI (3.11/3.13), tests, docs, board (#1).
- **OPS-4 Desktop launcher** — anchor icon on the desktop + app menu; starts the service if
  needed and opens the dashboard (`deploy/install-desktop-launcher.sh`). The script is installed to
  `~/.local/bin/boat-dashboard-open` so the icon works whatever branch the checkout is on (#2).
- **PWR-1 Victron monitoring** — SmartSolar, BMV-712, Orion XS decoded live; shared BLE
  scanner fixes BlueZ InProgress conflicts; energy-flow strip + cards. Keys outside the repo (#3).
- **PWR-0 JBD BMS over BLE** — both batteries live, reconnects, French UI, systemd service.
