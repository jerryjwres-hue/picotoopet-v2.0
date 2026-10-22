# PicotooPet P0 #91 — read-only Mac preflight at b6230da

Frozen video candidate: `b6230da62eb803e9a7be840374feeb481a657c3a`. Mac source product version: `2.3.27.1`. This document checks an **already deployed** Mac, never installs or starts Core/Ollama/Worker.

## Mac Terminal — minimal no-mutation inspection

Paste the following into a Mac Terminal. The expected Core port is **8766**, whereas the code default is **8765**: the *deployed* port is persisted in `state/api-port.txt`. Do not silently switch endpoints when they disagree. Run the commands only with the owner's permission and redact hostnames/paths if sharing output.

```bash
ROOT="$HOME/Library/Application Support/PicotooPetV2"
echo "UTC=$(date -u -u +%Y-%m-%dT%H:%M:%SZ)"
echo "DEPLOYED_PORT_RECORD:"
test -r "$ROOT/state/api-port.txt" && cat "$ROOT/state/api-port.txt" || echo UNVERIFIED

# A successful HTTP 200 is not enough: JSON status=ok AND database=ok are required.
curl --noproxy '*' --connect-timeout 3 --max-time 6 -fsS http://127.0.0.1:8766/api/v1/health

# Installed, resident and inference-completed are THREE different proofs.
curl --noproxy '*' --connect-timeout 3 --max-time 6 -fsS http://127.0.0.1:11434/api/tags |
  python3 -c 'import json,sys; print("OLLAMA_INSTALLED="+("PASS" if "gpt-oss:20b" in [x.get("name") for x in json.load(sys.stdin).get("models",[])] else "BLOCKED"))'
curl --noproxy '*' --connect-timeout 3 --max-time 6 -fsS http://127.0.0.1:11434/api/ps |
  python3 -c 'import json,sys; print("OLLAMA_RESIDENT="+("PASS" if "gpt-oss:20b" in [x.get("name") for x in json.load(sys.stdin).get("models",[])] else "BLOCKED"))'

# Show only status fields; full launchctl output can expose environment secrets.
for agent in com.picotoopet.mac-core com.picotoopet.worker com.picotoopet.health-supervisor; do
  echo "AGENT=$agent"
  launchctl print "gui/$UID/$agent" 2>/dev/null |
    grep -E '^[[:space:]]*(state|pid|last exit code) =' | head -3 || echo UNVERIFIED
done
PLIST="$HOME/Library/LaunchAgents/com.picotoopet.worker.plist"
if [ -f "$PLIST" ]; then
  plutil -lint "$PLIST"
  plutil -extract ThrottleInterval raw -o - "$PLIST" 2>/dev/null || echo "THROTTLE_UNVERIFIED"
else
  echo "WORKER_PLIST_UNVERIFIED"
fi

# SQLite SELECT only. If a WAL reader cannot open it, report BLOCKED, do not checkpoint.
DB="$ROOT/database/core.db"
if [ -r "$DB" ]; then
  sqlite3 -readonly "$DB" "PRAGMA journal_mode;
    SELECT 'QUEUE:'||status||':'||COUNT(*) FROM tasks GROUP BY status;
    SELECT 'OUTBOX_LAST_SEQ:'||COALESCE(MAX(rowid),0) FROM event_outbox;"
else
  echo "SQLITE_UNVERIFIED"
fi
```

**Read-only outcome (operator assigns after running):** Core health/status + DB `ok` + port=8766 => `PASS` for *Core*, otherwise `BLOCKED` if an approved deployment is expected, or `UNVERIFIED` if the Mac has never been deployed. Ollama tags contains model => installed PASS; ps contains model => resident PASS; neither proves successful inference. Already-documented authorized inference transcripts (model ID + timestamp + completion evidence) may prove **historical** inference without a new POST, but if none exists: `OLLAMA_ACTUAL_INFERENCE=UNVERIFIED`. Do not run `resident-check`, `ollama run`, `/api/generate`, or download weights: they can load model or generate tokens.

`launchctl print` verifies registered process state, **not** automatic restart after crash, wake or logout. Worker plist must have RunAtLoad=true, KeepAlive=true and ThrottleInterval >= 30 (the original b623 source lacked this last key; isolated branch fixes generation for a future authorized installation). Never run bootstrap/bootout/kickstart/kill/reboot in Stage 1.

**Authenticated worker and queue**: source-proven `GET /api/v1/workers/status` requires existing Bearer pairing and must show `state=online, available=true`, nonempty worker_id and fresh last_heartbeat_at with `autonomous.discovery.v1, autonomous.goal_synthesis.v1, autonomous.goal_creative.v1` as required by current local video workflow, if available; otherwise capability incomplete is BLOCKED for first video. `GET /api/v1/status` returns task_counts and services. Check via the **already paired Windows UI** or an approved internal authenticated client; do not print/retrieve/import a token for this check. 401 means credentials unverifiable, not proven Worker down. A Worker online check also doesn't prove Creative handler can create a valid plan.

**Windows LAN**: On Windows, read-only `Test-NetConnection <approved-Mac-LAN-IP> -Port 8766` validates TCP only; confirmed pairing requires real authenticated Windows UI request, and event loss recovery requires `/api/v1/events?after_sequence=<last_ack_sequence>` ordered replay plus fresh authority lookup. Mac localhost success is insufficient. No forced network disconnection in this stage; absent Windows evidence => UNVERIFIED.

## Same candidate Mac Core / Worker artifacts and rollback

Native GitHub CI at exact candidate HEAD b6230da: Core [39537234608](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39537234608) SUCCESS (artifact **12318227250**, MacCore SliceD arm64-3063; OpenAPI **12318227245**); Worker [39537234530](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39537234530) SUCCESS (artifact **12317567446**, MacWorker SliceD arm64-2996). Those original package labels contain GitHub synthetic PR merge SHA `5dc5763661582c62083860c9bd79fd3112ba402d`, whose Git tree `34e2edfae2bd07297fc908dcc4a4943544c68a04` is IDENTICAL to b6230da's tree; source content is equivalent but archive SOURCE_SHA labels do **not** name b6230da. This independent scope patch changes the two macOS workflow checkouts and version labels to exact PR head SHA for future auditable artifacts. The existing uploads are historical and not silently relabeled.

The approved scripts, **NOT to be executed now**, are: `deploy/macos/phase23/{INSTALL,VERIFY,ROLLBACK}_MAC_CORE_SLICE_B.command` and `deploy/macos/phase23-worker/{INSTALL,VERIFY,ROLLBACK}_MAC_WORKER_SLICE_C.command`. Verify release-manifest, tar SHA256, mac-build-report, wheelhouse and both Core+Worker source SHA/tree before **separately approved** install. On-disk rollback markers: `$ROOT/state/previous-version.txt` for Core; `$ROOT/state/slice-d-previous-version.txt`, `slice-d-previous-worker.plist`, and `slice-d-previous-worker-present.txt` for Worker. This rollback preserves DB/outbox but changes current symlink and LaunchAgents, so requires authorization.

**Current gate:** `P0_MAC_READY=UNVERIFIED` for actual user Mac, actual inference, 24-hour unattended service, restart, Windows LAN, and real video. Native CI fixture PASS is not physical evidence. User Windows breaker instability prohibits long GPU render until electrician clearance and separate authorization. Draft only; no install/model/network/device mutation, no merge/rebase/tag/release.
