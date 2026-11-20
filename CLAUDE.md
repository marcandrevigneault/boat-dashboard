# Boat Dashboard — working agreement

Onboard boat software: one polished app for system monitoring/control, NMEA 2000 (SeaTalkNG) devices,
charts, GPS, radar and weather routing. Target hardware: Raspberry Pi 5 (headless, behind the breaker
panel), viewed in a browser on tablets/phones/displays. Today it runs on a Celeron J3160 dev box.
The repo is **public**.

## Workflow (mandatory)
- Never commit to `main`. One branch per change: `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Every change lands via a GitHub PR using the template; CI must be green before merge. Squash-merge.
- Small PRs: one feature or refactor each. Commit messages in imperative mood.
- Update `docs/BOARD.md` (planning) and the relevant `docs/systems/*.md` (how it works) in the same PR.
- Architecture decisions go in `docs/adr/NNNN-title.md` (short: context, decision, consequences).

## Quality bar
- Python: `ruff check`, `ruff format`, `mypy --strict`, `pytest` (coverage gate in pyproject) must pass.
- Hardware protocols are tested with recorded/constructed frames — tests never need real devices.
- Performance matters (Pi target): bounded buffers, no polling faster than the data changes, send
  only changed values to clients, no full-DOM re-renders.
- **Aesthetics are a priority**: consistent design tokens, day + night (red) modes, readable at a
  glance in sunlight, works from phone width to large displays, smooth transitions, no layout jumps.

## Never commit
Passwords, API keys, device encryption keys (e.g. Victron), or the boat's position/tracks.
Local secrets live in untracked files (see `.gitignore`).

## Useful commands
    .venv/bin/pip install -e '.[dev]'
    .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy && .venv/bin/pytest
    sudo systemctl restart boat-dashboard     # service runs the app on :8080
