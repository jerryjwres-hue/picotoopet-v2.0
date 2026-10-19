# P0-C Mac Unattended Readiness — Issue #93

Frozen baseline: `b1977ffc36d9151e1b8ff17d369583d0ed0e0334`  ·  Owner: `test/p0-mac-unattended-readiness-v1`

## Gate (P0_MAC_READY)

| Component | macOS CI criterion | Required real-Mac acceptance |
| --- | --- | --- |
| LaunchAgent install | Generate worker plist from existing installer library; native `plutil`; `RunAtLoad`, `KeepAlive`, 30s restart throttle, executable path, background status | `launchctl print gui/$UID/com.picotoopet.worker` after consented installation and a real login/reboot |
| Worker startup / stop | Real `picotoopet-core worker --loop` subprocess starts, drains queue, handles SIGTERM | Native `launchctl` bootstrap/bootout and automatic relaunch after termination |
| Ollama | Fake HTTP contract tests: gpt-oss:20b installed/running, preload with `keep_alive=-1`, missing model and unavailable server fail closed | Ollama real `/api/tags`, `/api/ps`, `resident-check` on user Mac; recovery without manual command |
| Queue + retries | Actual SQLite WAL; two simulated expired leases (retry 2/2 and bounded failed 1/1); queued `analysis` remains untouched | Sleep/wake/power recovery and durable on-disk artifacts |
| Worker restart | Terminate a real Worker, close/reopen SQLite, launch a new Worker ID, drain previously committed task | Real LaunchAgent auto-restart; verify no duplicate terminal commits |
| Windows LAN disconnect | Authorized WebSocket with `after_sequence` replays missing ordered Outbox events after simulated disconnect | Actual Windows-only reconnection/preview after offline period |
| 24-hour operation | **UNVERIFIED**: minute-long CI is not 24 hours | 24h uninterrupted real-Mac observation, timed logs and model/queue checkpoints |

**P0_MAC_READY=PASS** requires every real-Mac row PASS, plus no unbounded restart loop, no queue loss, and no manual intervention after approved one-time install. Native CI PASS is *bounded readiness evidence*, never a claim of 24-hour uninterrupted operation. No real Mac evidence means **P0_MAC_READY=UNVERIFIED**. Fail the gate if any critical real requirement fails.

## Execution

CI: `.github/workflows/p0-mac-unattended-readiness.yml` runs on GitHub macOS `macos-15` and uploads pytest JUnit proof for its commit. Equivalent developer-only command: `python -m pytest -q tests/p0_mac_unattended` after installing the project in a Python 3.12 environment. The suite does **not** install LaunchAgents, run launchctl mutations, download Ollama models, contact Windows or read the user's data.

Before installing on the user's Mac, obtain explicit permission and a tested rollback. Existing user-authorized entry points only: `deploy/macos/phase23-worker/INSTALL_MAC_WORKER_SLICE_C.command`, `VERIFY_MAC_WORKER_SLICE_C.command`, `ROLLBACK_MAC_WORKER_SLICE_C.command`. A LaunchAgent under `~/Library/LaunchAgents` only starts in the logged-in user's session; it does **not** guarantee execution while logged out, Mac asleep, powered off, or after a model-host crash. Keep hardware awake/online via user-approved settings; never change them silently.

## Windows-only daily diagnostics — proposal for #91, no implementation in this ownership

Use existing Mac Core API + authenticated /events WebSocket and persistent Outbox; **do not create a second queue**. Surface a five-field non-secret status panel inside the existing Windows Goal Center: (1) Mac Core health (`GET /api/v1/health`), (2) local-model readiness (existing capability/health projection; UNVERIFIED if no authoritative status), (3) Worker state/available/heartbeat (`GET /api/v1/workers/status`), (4) last received Outbox sequence and gap/replay state (`/api/v1/events?after_sequence=<last_acknowledged>`), (5) queued/retrying/running task counts (`GET /api/v1/status`). Use existing bearer authentication; never log token, file payloads or raw prompts. After Windows reconnect, replay by persisted sequence and independently re-query authoritative task status; do not infer completion from a dropped socket. Show offline/stale/UNVERIFIED distinctly.

## Safety / reporting

- CI cannot prove LaunchAgent GUI bootstrap, model GPU residency or actual 24h operation. Distinguish **PASS**, **FAIL**, **UNVERIFIED** per row and attach the real run URL, exact SHA and native job outcome.
- No end-user install, user Mac access, firewall, credentials, paid provider, model download or global service was changed.
- The sole deployment change adds `ThrottleInterval=30` to the existing generated Worker LaunchAgent definition. Rollback: restore the saved prior plist using the existing rollback workflow after user approval; no database reset. Do not edit the read-only Core / Health Supervisor plists.
- If `gpt-oss:20b` or required dynamic Creative/Production handler is absent in production, report the missing capability to #91/G006. Do **not** register a mock or widen task-type ownership here.
