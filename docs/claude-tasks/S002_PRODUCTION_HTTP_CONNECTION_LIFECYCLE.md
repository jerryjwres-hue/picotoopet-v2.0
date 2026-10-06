# S002 — Production HTTP Connection Lifecycle

Goal: reduce Windows -> Mac Core TCP churn during Production/autopilot without changing Production semantics.

Branch: fix/production-http-connection-lifecycle
Baseline: cc4c02aa28d816ecf3d2013346da03678c06bc63

Known fact:
ControlCenterSession.Production.cs currently creates and disposes a MacCoreProductionClient for each Production API call.
MacCoreProductionClient.Create() creates a fresh SocketsHttpHandler + HttpClient each time.
C003 autopilot can issue claim/attempt/heartbeat/result/package calls during one render, so this discards connection pools unnecessarily.

Required implementation:
1. Reuse one long-lived MacCoreProductionClient for the active ControlCenterSession connection/pairing lifecycle.
2. Do not create/dispose a Production HTTP client for every API operation.
3. On reconnect/address/token replacement:
   - dispose the old Production client safely
   - create/use one bound to the new base URI + current token
   - never reuse stale address/token
4. Concurrent Production API calls safely share the live HttpClient pool.
5. Existing auth headers, trace IDs, bounded response handling, timeouts and API semantics stay unchanged.
6. Do not persist token/address anywhere new.
7. Session dispose closes the Production client exactly once.
8. Failed connection/replacement must not leak a client.

Do not:
- change Production lifecycle or C003 autopilot semantics
- change Core backend
- change ComfyUI endpoint/workflows/models
- add arbitrary endpoint/path inputs
- touch Goal final-video assembly files (Codex C004 owns those)
- touch Mac Worker/Ollama
- touch deploy/macos
- touch Natural Motion/torso gate

Expected surface:
- windows/desktop/src/PicotooPet.Desktop/Services/ControlCenterSession.Production.cs
- minimal lifecycle hook in ControlCenterSession.cs only if necessary
- MacCoreClient.Production.cs only for a small lifecycle/test seam
- focused Windows smoke tests
Do not broaden the diff.

Tests must prove:
- multiple Production API operations in one active session reuse one client/handler
- concurrent operations do not create duplicate pools
- reconnect disposes old client and uses new base/token
- session dispose closes once
- failed setup does not leak
- existing Production auth/trace/bounded-response tests stay green
- C003 autopilot tests stay green
- Windows solution build + Windows Control Center CI

Delivery requirements:
- commit all S002 changes
- push to origin/fix/production-http-connection-lifecycle
- do not rebase, merge, tag, or release
- working tree clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
root cause
architecture notes
residual risk
git status --short
