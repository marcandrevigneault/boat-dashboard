# Boat Dashboard — working agreement

This file is the single source of truth for **how** work is done on this project. It applies to every
session, every resume after a reset, and every sub-agent. When delegating to a sub-agent, tell it to
read this file first. If a rule here conflicts with habit or with an older memory, this file wins;
change the method by editing this file in a PR, never silently.

Onboard boat software: one polished app for system monitoring/control, NMEA 2000 (SeaTalkNG) devices,
charts, GPS, radar and weather routing. Target hardware: Raspberry Pi 5 (headless, behind the breaker
panel), viewed in a browser on tablets/phones/displays. Today it runs on a Celeron J3160 dev box.
The repo is **public**.

## Session start (every time, including after a reset)
1. `git status -sb && git fetch -q && gh pr list` — find unfinished branches and open PRs.
2. Read `docs/BOARD.md` → the **In progress** column says what is being worked on and the next step.
3. Read `docs/ARCHITECTURE.md` and the `docs/systems/*.md` for the area you will touch.
4. Continue the in-progress item before starting anything new, unless the owner says otherwise.

## Session end / before a disconnect
- Commit and push everything on the feature branch (a `WIP:` commit is fine on a feature branch).
- Open the PR as a draft if the work isn't finished.
- Update the In-progress item on `docs/BOARD.md` with status, branch/PR number and the exact next step,
  so the next session (or another agent) can resume without asking.

## Workflow (mandatory)
- Never commit to `main`. One branch per change: `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Every change lands via a GitHub PR using the template; CI must be green before merge. Squash-merge.
- Small PRs: one feature or refactor each. Commit messages in imperative mood.
- Update `docs/BOARD.md` (planning) and the relevant `docs/systems/*.md` (how it works) in the same PR.
- Architecture decisions go in `docs/adr/NNNN-title.md` (short: context, decision, consequences).
- Board item IDs (e.g. `NAV-1`) go in the PR title or body.

## Test tiers — pick one per PR and state it in the PR body
**Light** — small UI-only changes: styling, spacing, colours, copy/wording, icons, layout tweaks in
one view. No logic, data-flow, API or dependency changes.
- Run: lint + format + type checks, unit tests for anything touched.
- Visual check: screenshots in day **and** night mode at phone and tablet width.
- Skip the full end-to-end suite. Label the PR `light-tests`; CI then skips the E2E job.

**Full** — everything else: new features, backend or protocol code, data model, WebSocket/API
contracts, config, dependencies, CI, performance-sensitive code, or any UI change that touches state
or data flow. When in doubt, it's Full.
- Run: lint + format + type checks, the whole unit/integration suite with the coverage gate, the E2E
  suite (once it exists), and a performance/memory check for long-running code paths (no unbounded
  growth; CPU reasonable on the Pi).

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
