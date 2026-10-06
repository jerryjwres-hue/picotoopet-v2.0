# C004 — Goal Final Video Assembly & Delivery

## Goal

Close the final local product gap after C003.

Current durable Production output is a set of per-shot WebM files recorded in Production Package v1. The package ZIP contains provenance JSON only; it does not contain the actual media bytes.

C004 must turn the verified ordered shot outputs into one local final video and surface it in Goal Center.

Target flow:

Goal -> C001/C002 -> Production job -> C003 autopilot render -> production_ready ->
verify local shot outputs -> fixed local FFmpeg assembly -> final MP4 -> Goal Center "成品已就绪"

No publishing/uploading is part of C004.

## Branch

Work only on:
`feature/goal-final-video-assembly`

Baseline:
`cc4c02aa28d816ecf3d2013346da03678c06bc63`

## Existing components — MUST reuse

- GoalVideoContinuationRecord / GoalVideoContinuationViewModel
- GoalProductionAutopilotCoordinator
- ProductionExecutionService
- ControlCenterSession.GetProductionPackageAsync
- ProductionPackageRecord manifest
- existing trusted Comfy data-root/output-root detection and path/symlink protections
- Core Production Package output SHA-256 / mime / width / height / frame_count / fps facts

Do not add a second Production lifecycle or renderer.

## Required behavior

### 1. Trigger only from the current Goal

When the current completed video Goal reaches `production_ready` and has a Production Job ID:

- fetch the existing Production Package for exactly that job
- do not scan arbitrary jobs
- start final assembly asynchronously/non-blocking
- at most one assembly task per production job at a time
- repeated Goal Center refreshes must not launch duplicates

### 2. Verify every source shot before FFmpeg

Use the Production Package manifest outputs in stored list order.

For every output:
- require a bounded relative `output_relpath`
- resolve only below the trusted Comfy output root
- reject traversal/rooted paths
- reject symlink/reparse escape using the same production safety boundary
- require existing ordinary file
- require expected mime to be local video output
- recompute SHA-256 and compare with Core package `output_sha256`
- do not assemble if any source is missing or mismatched

Do not trust arbitrary Windows/UI-supplied file paths.

### 3. Fixed FFmpeg assembly

Use only a fixed executable identity:
- `ffmpeg.exe` discovered from the normal trusted PATH
- no executable path supplied by Core, Goal, package, user, or config

Use fixed internally-authored arguments.
No arbitrary command/argument injection.

Create one final MP4 in a PicotooPet-managed Windows directory, preferably:
`%LOCALAPPDATA%\PicotooPet\FinalVideos`

Filename must be derived only from the production job identity and sanitized/deterministic.

The final output must be suitable for ordinary Windows playback.
Do not mutate/delete the source WebM files.

If shot properties make safe deterministic assembly impossible, fail with a bounded local status rather than guessing.

### 4. Immutable/restart-safe local final result

Add a small local final-video manifest beside the final MP4 containing only bounded provenance such as:
- schema version
- production job id
- production package id/digest
- ordered source output hashes
- final file relative/name identity
- final SHA-256
- final bytes
- created_at

Do not persist prompts, tokens, arbitrary paths, credentials, or raw package JSON.

If the same production package is observed after restart:
- reuse an already verified matching final MP4 + manifest
- do not reassemble unnecessarily
- conflicting existing output/manifest must fail closed

### 5. Goal Center UX

In Goal Center:
- keep manual Web GPT return flow unchanged
- keep C003 Production autopilot unchanged
- while assembling: bounded text such as "正在合成最终视频"
- success: "最终视频已就绪"
- failure: bounded safe text
- add one explicit user action to open the final video or its managed folder
- opening happens only on user click
- never display raw local absolute paths in normal status text
- no automatic upload/publish

### 6. Manual Production panel remains

Do not remove or duplicate the Production panel.

## Architecture / security invariants

- Mac Core remains durable source of truth for Goal/Creative/Production.
- Windows final assembly is a derived local artifact only.
- No new Core DB table is required.
- No provider/model/workflow/endpoint/path/command authority from payloads.
- No shell script generation from untrusted data.
- No auto publish.
- Research Gateway remains read-only.
- Do not touch Mac Worker/Ollama lifecycle code.
- Do not touch deploy/macos.
- Do not touch Natural Motion / torso gate.
- Do not change Production Package semantics unless a missing contract is proven. If backend change appears necessary, stop and report first.

## Suggested implementation surface

Prefer Windows-only files outside Claude S002 connection-lifecycle scope:
- new final video assembly/delivery service under `windows/desktop/src/PicotooPet.Desktop/Services/`
- refactor shared trusted Production local-environment/path validation out of ProductionExecutionService only if needed
- GoalVideoContinuationViewModel / Goal Center presentation
- focused smoke tests

Avoid modifying:
- `MacCoreClient.Production.cs`
- `ControlCenterSession.Production.cs`
Those files are reserved for Claude S002.

## Tests required

At minimum:

1. Source verification
- ordered package outputs are preserved
- traversal/rooted path rejected
- symlink/reparse escape rejected
- missing file rejected
- hash mismatch rejected
- source files are never deleted/modified

2. Assembly coordinator
- production_ready starts one non-blocking assembly
- repeated observations do not duplicate
- non-terminal production statuses do not assemble
- Goal switch ignores stale completion
- dispose cancels/ignores late completion
- restart reuses matching verified final artifact
- conflicting existing final artifact fails closed

3. FFmpeg boundary
- fixed `ffmpeg.exe` identity
- fixed argument construction only
- no package/user-supplied executable/command/path authority
- nonzero exit / timeout maps to bounded safe failure

4. Goal Center
- final state is mapped, not raw exception/path text
- open action only enabled for verified final artifact
- open occurs only by explicit user click
- existing C002/C003 behavior remains

5. Regression
- Windows solution build
- C002 smoke tests
- C003 autopilot tests
- existing Production smoke tests
- Windows Control Center CI

## Residual real-machine acceptance

Automated CI cannot prove real GPU media correctness.
Report clearly that real Windows validation still must confirm:
- ffmpeg present
- real rendered WebM inputs
- produced MP4 opens and plays

## Delivery requirements

After implementation and required tests:
- commit all C004 changes
- push the current branch to `origin/feature/goal-final-video-assembly`
- do not rebase
- do not merge
- do not tag
- do not release
- working tree must be clean

Final response only:
remote branch
remote HEAD SHA
files changed
tests
architecture notes
residual risk
git status --short
