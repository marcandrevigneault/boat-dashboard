# 0001 — Stack and data model

**Status:** accepted (2026-11-20)

## Context
Long-lived product spanning power monitoring, NMEA 2000, charts, radar and weather routing.
Must run on a Raspberry Pi 5 hidden behind the breaker panel, be viewed from several screens,
and work fully offline.

## Decision
- **Backend:** Python 3.11+ with asyncio + FastAPI. Good BLE (bleak), CAN (python-can) and
  scientific libraries for routing. Strict typing (mypy) and ruff.
- **UI:** web app served by the backend, so any tablet/phone/display is a screen and the Pi
  can stay headless.
- **Data model:** Signal K paths and SI units for every value, so a Signal K server can be a
  source or a consumer without translation.
- **Charts:** our own chart view on MapLibre GL (not OpenCPN), for a single consistent UI.
  Chart data converted offline to tiles (ADR to follow with CHART-1).

## Consequences
- Need a frontend build step once the UI grows (decided in UI-1).
- Radar and NMEA 2000 decoding reuse open-source decoders where they exist instead of
  reimplementing them.
