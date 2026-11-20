# Boat Dashboard

Onboard dashboard for the boat computer (`navcentral`). Served on port 8080, so it can be opened from any device on the boat's Wi-Fi.

## Current features
- Live readings from JBD-style Bluetooth BMS (Batterie A, Batterie B): SOC, voltage, current, power, cells, temperature, protection alarms
- Combined battery-bank summary with remaining runtime / time to full
- Night (red) mode

## Run
    python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
    .venv/bin/python -m boatdash.server
Devices are configured in `config.json`. One-off BMS test: `.venv/bin/python scripts/bms_test.py <MAC>`.

To start at boot: `deploy/boat-dashboard.service` (systemd).

## For developers
Read `CLAUDE.md` (workflow and quality bar), `docs/ARCHITECTURE.md`, and `docs/BOARD.md` (plan).
