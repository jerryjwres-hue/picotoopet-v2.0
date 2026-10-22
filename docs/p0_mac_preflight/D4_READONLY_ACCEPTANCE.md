# P0 #91 — d4c27883 Mac-only native artifact + strictly read-only deployment preflight

**Frozen candidate:** `d4c27883d8988dbb7ab1670c598d5a3b8c8ed384`. **Product version:** `2.3.27.1`. **Python wheel package version:** `2.3.0.dev2`. **Evidence-only document:** no installed service changes, secrets, token reads, live model inference, reboot, install, rollback, Git merge or release.

## 1. Exact candidate arm64 artifacts (GitHub-native, 2026-10-22 UTC)

| Artifact identity | Core | Worker |
|---|---|---|
| Native GH workflow run | [39705258654](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39705258654) SUCCESS | [39705258695](https://github.com/jerryjwres-hue/picotoopet-v2.0/actions/runs/39705258695) SUCCESS |
| Job ID (native macos-15-arm64) | `119583728426` | `119583735696` |
| Artifact ID | `12395435349` | `12395445373` |
| Artifact name | `PicotooPet-MacCore-SliceD-arm64-3069` | `PicotooPet-MacWorker-SliceD-arm64-3002` |
| GitHub *outer* artifact ZIP SHA256 | `2314a45b999acaac88c3f1de63f678ba94f8b4df801613b55756e20839230246` | `f70d768643b54e20c06f15be8b9b7b019ab03baa5caee96a45b402b5dc4d12b8` |
| *Inner* offline tar.gz SHA256 in native job log | `d354cfd223ace44f071909f8d529eba0fc8cf1c3224ecb32a5fe298b0f85a894` | `acabdcafb9fa8697e249b79dd0d64f3097981ca52f5ef7ca418388901f375c26` |
| Inner tar.gz basename | `PicotooPet-MacCore-2.3.27.1-2.3.0-slice-d-core-3069-d4c27883d8988dbb7ab1670c598d5a3b8c8ed384-arm64.tar.gz` | `PicotooPet-MacWorker-2.3.27.1-2.3.0-slice-d-worker-3002-d4c27883d8988dbb7ab1670c598d5a3b8c8ed384-arm64.tar.gz` |
| Native test/fixture result | package/install/verify/rollback PASS | package/install/verify/expired lease/cancel/rollback PASS |

Native checkout logged fetching exact d4 HEAD, build `--version-label` embeds d4, both package builders obtain `commit` via `git rev-parse HEAD` and embed in `release-manifest.json` and `mac[-worker]-build-report.json`. A fixture PASS is not proof of actual Mac installation. Inner tar hashes **differ** from GitHub uploaded outer ZIP hashes. Reject an archive if the artifact ID, SOURCE_SHA, product version or both independent checks do not match the intended d4 candidate; historical `b6230da...`, independent `6d1ecaa...` (#122) and synthetic PR `5dc576...` are not valid d4 identifiers even when an earlier tree matches.

### Manifest/source validation of *already downloaded* packages only

The following only reads existing local archives; set the two variables to the exact files already downloaded. It never downloads, unpacks to disk or installs anything. If a file is absent, classify `UNVERIFIED`.

```bash
# ── Select EXISTING local tarballs; never substitute a similarly named old package. ──
CORE_TAR="/absolute/path/to/existing/MacCore-d4-arm64.tar.gz"
WORKER_TAR="/absolute/path/to/existing/MacWorker-d4-arm64.tar.gz"
EXPECTED_SHA="d4c27883d8988dbb7ab1670c598d5a3b8c8ed384"
for role in CORE WORKER; do
  # ── Keep the outer GitHub ZIP digest distinct from the tarball's digest. ──
  if [ "$role" = CORE ]; then file="$CORE_TAR"; expected_hash="d354cfd223ace44f071909f8d529eba0fc8cf1c3224ecb32a5fe298b0f85a894"
  else file="$WORKER_TAR"; expected_hash="acabdcafb9fa8697e249b79dd0d64f3097981ca52f5ef7ca418388901f375c26"; fi
  if [ ! -f "$file" ]; then echo "$role=UNVERIFIED (archive absent)"; continue; fi
  actual_hash="$(shasum -a 256 "$file" | awk '{print $1}')"
  if [ "$actual_hash" != "$expected_hash" ]; then echo "$role=BLOCKED (tar SHA mismatch)"; continue; fi
  manifest_path="$(tar -tzf "$file" | grep '/release-manifest.json$' | head -1)"
  if [ -z "$manifest_path" ]; then echo "$role=BLOCKED (manifest missing)"; continue; fi
  tar -xOzf "$file" "$manifest_path" |
    python3 -c 'import json,sys; m=json.load(sys.stdin); expected=sys.argv[1]; ok=(m.get("commit")==expected and m.get("product_version")=="2.3.27.1" and m.get("architecture")=="arm64" and m.get("source_build_on_user_mac") is False); print("MANIFEST="+("PASS" if ok else "BLOCKED")+" release_type="+str(m.get("release_type"))+" runtime="+str(m.get("runtime_version")))' "$EXPECTED_SHA"
done
```

`release-manifest.json.files[]` enumerates in-package file SHA256/size, and CI `Test-Mac*Slice*.sh` verifies those; the snippet checks top-level identity but **does not substitute for file-by-file manifest verification** or matching `mac-build-report.json` / `*.sha256.txt`. If actually installing later, an authorized installer must perform those already-existing checks.

## 2. User Mac terminal read-only audit (never execute .command installers)

Paste only on an **already deployed** Mac, after owner permission. There are no `launchctl kickstart/bootstrap/bootout`, `ollama run`, model POST, `sqlite` writes, `pip` installation or downloads. This script reports only non-secret state and does not read an API token.

```bash
# ── Static identity / deployed path; no local mutation. ──────────────────────
ROOT="$HOME/Library/Application Support/PicotooPetV2"
echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "MAC_ARCH=$(uname -m)"
test -r "$ROOT/state/api-port.txt" && printf 'DEPLOYED_PORT=' && cat "$ROOT/state/api-port.txt" || echo 'DEPLOYED_PORT=UNVERIFIED'
for name in current state/previous-version.txt state/slice-d-previous-version.txt state/slice-d-previous-worker-present.txt; do
  # ── Historical rollback markers do NOT themselves prove rollback tested here. ──
  [ -e "$ROOT/$name" ] || [ -L "$ROOT/$name" ] || { echo "$name=UNVERIFIED"; continue; }
  ls -ld "$ROOT/$name"
done

# ── Core HTTP health / DB response: public GET without credentials. ─────────
curl --noproxy '*' --connect-timeout 3 --max-time 6 -fsS http://127.0.0.1:8766/api/v1/health |
  python3 -c 'import json,sys; h=json.load(sys.stdin); print("CORE_HEALTH="+("PASS" if h.get("status")=="ok" and h.get("database")=="ok" and h.get("version")=="2.3.27.1" else "BLOCKED"), "version="+str(h.get("version")))' ||
  echo "CORE_HEALTH=UNVERIFIED (GET failed)"
lsof -nP -iTCP:8766 -sTCP:LISTEN 2>/dev/null | awk 'NR==1 || NR==2 {print}' || true

# ── Model installed and model loaded are NOT proof of completed inference. ───
for endpoint in tags ps; do
  curl --noproxy '*' --connect-timeout 3 --max-time 6 -fsS "http://127.0.0.1:11434/api/$endpoint" |
    python3 -c 'import json,sys; names=[m.get("name") for m in json.load(sys.stdin).get("models",[])]; print("gpt-oss:20b="+("PRESENT" if "gpt-oss:20b" in names else "NOT_OBSERVED"))' ||
    echo "OLLAMA_$endpoint=UNVERIFIED (GET failed)"
done
echo 'OLLAMA_COMPLETED_INFERENCE=UNVERIFIED unless pre-existing provenance timestamp/output exists'

# ── LaunchAgent: project only state; never print full environment or plist. ──
for agent in com.picotoopet.mac-core com.picotoopet.worker com.picotoopet.health-supervisor; do
  echo "AGENT=$agent"
  launchctl print "gui/$UID/$agent" 2>/dev/null |
    grep -E '^[[:space:]]*(state|pid|last exit code) =' | head -3 || echo "AGENT_STATE=UNVERIFIED"
done
PLIST="$HOME/Library/LaunchAgents/com.picotoopet.worker.plist"
if [ -f "$PLIST" ]; then
  plutil -lint "$PLIST"
  for field in RunAtLoad KeepAlive ThrottleInterval; do
    printf '%s=' "$field"
    plutil -extract "$field" raw -o - "$PLIST" 2>/dev/null || echo 'UNVERIFIED'
  done
else echo 'WORKER_PLIST=UNVERIFIED'; fi

# ── JSON status file: print capability names/state, not IDs or secrets. ─────
if [ -r "$ROOT/state/worker-status.json" ]; then
  python3 - "$ROOT/state/worker-status.json" <<'PY'
import json
import sys
from pathlib import Path
s = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
types = s.get("supported_task_types", [])
required = {"autonomous.discovery.v1", "autonomous.goal_synthesis.v1", "autonomous.goal_creative.v1"}
print("WORKER_STATE=", s.get("state"))
print("CREATIVE_CAPABILITIES=", "PASS" if isinstance(types, list) and required.issubset(set(types)) else "UNVERIFIED_OR_BLOCKED")
print("LAST_HEARTBEAT=", s.get("last_heartbeat_at", "UNVERIFIED"))
PY
else echo 'WORKER_STATUS=UNVERIFIED'; fi

# ── Read-only SQLite access: do not checkpoint, vacuum, migrate or update. ──
DB="$ROOT/database/core.db"
if [ -r "$DB" ]; then
  sqlite3 -readonly "$DB" "SELECT 'DB_READ='||CASE WHEN (SELECT 1)=1 THEN 'PASS' ELSE 'BLOCKED' END;
    SELECT 'OUTBOX_COUNT='||COUNT(*) FROM event_outbox;
    SELECT 'TASK_STATUS='||status||':'||COUNT(*) FROM tasks GROUP BY status;" ||
    echo 'DB_OR_OUTBOX=UNVERIFIED (query failed, no repair attempted)'
else echo 'DB_OR_OUTBOX=UNVERIFIED (db unreadable)'; fi
```

**Interpretation:**
- Public Core `GET /api/v1/health` with `status=ok`, `database=ok`, `version=2.3.27.1`, deployed port record `8766`, and expected LAN listener is **local runtime health only**. HTTP 200 without exact fields is not PASS.
- No-Bearer request cannot prove authenticated `GET /api/v1/workers/status`, actual Windows pairing or live event replay. Use a separately approved, already authenticated **Windows application** observation; do not read or print credentials. Mac localhost listening on `127.0.0.1` does not prove Mac LAN is reachable.
- `ollama /api/tags` proves model registered; `/api/ps` proves loaded/resident when present; neither proves infer was ever successfully completed. Existing timestamped genuine inference result may prove *historical* inference only; without it **OLLAMA_ACTUAL_INFERENCE=UNVERIFIED**. Do not send `/api/generate`.
- `launchctl print` and `plutil` prove current registration/config, **not** unattended crash/wake/logout restart. `KeepAlive=true`, `RunAtLoad=true`, `ThrottleInterval>=30` are necessary configuration conditions, not 24-hour recovery proof.
- `sqlite3 -readonly` queries historical DB facts only. Read failure or stale outbox is not proof of corruption and does not authorize fixes. A changed environment may need owner-provided alternate root without guessing.
- Runtime version from `health.version` alone cannot reveal exact deployed source SHA: preserve the associated verified package hash, manifest and installation report to tie user Mac to d4.

## 3. Deployment / rollback preflight checklist (operator, NOT executable here)

| Timing | Required check | PASS only when |
|---|---|---|
| Before | Mac Core and Worker provenance | Both artifact run `head_sha=d4`; outer ZIP and inner tar hashes above; internal manifests `commit=d4`, `product_version=2.3.27.1`, `architecture=arm64` and listed files hashes valid |
| Before | Existing deployment inventory | Current symlink target, `api-port.txt`, service/Worker health, LaunchAgent plist and previous-version markers recorded with no secrets |
| Before | Rollback viability | Previous targets remain present inside `versions`; Worker previous plist/present flag are consistent; rollback data DB/outbox left in place |
| Before | Source identity parity | Worker and Core artifacts **both d4**. Never combine a d4 Core with #122 / synthetic SHA Worker and call them same-source |
| After separately approved install | Artifact-to-runtime | Installed `current` target/report trace to exact approved archive; `health.version=2.3.27.1`; Worker version/capabilities consistent; no unapproved rollback markers modified |
| After separately approved install | First-video capabilities | Authenticated Worker online; `autonomous.goal_creative.v1`, discovery, synthesis present; successful local inference separately proven if ever authorized |
| After separately approved install | Pairing | Windows authenticates over approved LAN address to Core :8766. Local TCP check by itself never proves pairing |
| If an authorized rollback occurs | Restoration | Record previous/current symlink and prior plist state, restored service/Worker identities and health, previous DB/outbox preserved; existing `ROLLBACK_MAC_CORE_SLICE_B.command` and `ROLLBACK_MAC_WORKER_SLICE_C.command` handle mutations and must **not** be invoked by this document |

**New narrow finding:** In d4, `worker-lib.sh` already permits legal `autonomous.goal_creative.v1`, but `VERIFY_MAC_WORKER_SLICE_C.command` repeated its own allowlist **without that type**, incorrectly classifying a legitimate dynamically healthy Worker as unexpected. Scoped test/fix branch `fix/p0-mac-verify-goal-creative-allowlist-d4-v1` adds only that exact allowed type and one disposable-status-file test (approved vs unapproved type). **Original d4 packages predate this change; do not relabel them as patched**. A subsequent native Mac CI and replacement artifact on a new integrated SHA are needed before using the corrected verifier operationally.

**User Mac status:** `LIVE_MAC_CORE=UNVERIFIED`; `OLLAMA_INSTALLED=UNVERIFIED`; `OLLAMA_RESIDENT=UNVERIFIED`; `OLLAMA_ACTUAL_INFERENCE=UNVERIFIED`; `LAUNCHAGENT_RESTART_LIVE=UNVERIFIED`; `SQLITE_OUTBOX_LIVE=UNVERIFIED`; `WINDOWS_LAN_PAIRING=UNVERIFIED`. No user-machine actions in this review.
