# Final Video E2E Acceptance Preparation v1

Status: **PREPARED / UNVERIFIED** — preparation is not Windows acceptance.
Branch: `test/final-video-e2e-acceptance-v1`
Baseline: `feature/goal-master-delivery-selector-v1` @ `0271ff189f9ca184a844dbfd0a4158307986cbac`

## Source-of-truth audit

- C004: `FinalVideoAssemblyService`, `FinalVideoArtifact`, `FinalVideoAssemblyServiceSmokeTests`, `GoalFinalVideoCoordinatorSmokeTests`.
- C007B: `WindowsNarrationSynthesisService`, `NarrationSynthesisSmokeTests`, `NarrationRealWindowsSmokeTests`; plan contract in `src/picotoopet_core/postproduction/narration.py`.
- C008B: `WindowsCaptionOverlayService`, `PicotooPet.CaptionOverlay.SmokeTests` (contract/client, font, render, real ffmpeg); plan contract in `src/picotoopet_core/postproduction/captions_overlay.py`.
- C009A: `PostProductionMasterCompositorService`, `PostProductionMasterArtifactCatalog`, `PostProductionMasterSourceVerifier`, `PostProductionMasterContracts` and `PicotooPet.PostProductionMaster.SmokeTests`.
- C009B: `FixedFfmpegMasterVideoComposer`, `MasterVideoMediaProbe`, `PicotooPet.PostProductionMasterMux.SmokeTests` (unit + real Windows).
- C009C: `docs/architecture/video/C009C_IMPLEMENTATION_BRIEF_V1.md`; baseline contains no `PostProductionDeliveryCoordinator.cs`, `GoalDeliveryContracts.cs` or C009C isolated smoke suite. Integration is BLOCKED pending landing/wiring.
- C010A: frozen brief `docs/architecture/video/C010A_IMPLEMENTATION_BRIEF_V1.md` read from `design/c010a-implementation-brief-v1` @ `a1254477229aacfc2ba2db11b83d68eba7c3b185`; baseline has no C010A final QA/receipt implementation. The brief is design evidence, **not** runtime evidence.
- G006/G007: no files with those names exist on selected baseline tree; do not claim audited frozen requirements. Cross-check authoritative versions before activating tests.
- Additional upstream task references: `docs/codex-tasks/C004_GOAL_FINAL_VIDEO_ASSEMBLY.md`, `docs/codex-tasks/C007B_WINDOWS_LOCAL_NARRATION_SYNTHESIS.md`, `docs/claude-tasks/C008B_WINDOWS_CAPTION_OVERLAY_RENDER.md`, `docs/codex-tasks/C009A_POSTPRODUCTION_MASTER_CONTRACTS.md`, `docs/claude-tasks/C009B_POSTPRODUCTION_MASTER_FFMPEG_MUX.md`, `docs/gpt-tasks/C009C_DELIVERY_IMPLEMENTATION.md`.

## Acceptance invariants

A. Required = NarrationPlan.Plan.NarrationRequired OR OverlayPlan.Plan.OverlaysRequired. With neither, the **exact verified C004** is sole fallback candidate; with either, **exact verified C009 master** is mandatory and C004 fallback is forbidden. Caption support is not equivalent to overlays: current C010A v1 explicitly rejects CaptionsRequired or nonempty Captions as `FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`. The requested “仅字幕” and “旁白+字幕” scenarios must therefore separately track *text-overlay supported* versus *true captions unsupported*.

B. Preserve GoalId, handoff/return SHA, creative package/digest, production job/package/plan digest, output profile, runtime, selected C004/C008B visual, narration/overlay plan digests, all WAV segment identities, both upstream manifest SHA values, C009 MasterInputDigest, final file SHA+bytes and receipt digests. Recompute rather than trust caller-repeated strings.

C. C009A managed master directory is `%LOCALAPPDATA%\PicotooPet\PostProduction\Master\v1\<safe-job-prefix>-<job-sha16>\<MasterInputDigest>\` with **only** `master.mp4` and `master-manifest.json`. C004 `FinalVideos`, C007B `Narration\v1`, C008B `PostProduction\TextOverlay\v1` are upstream authorities. Never pick newest file, arbitrary path, directory scan or user-supplied artifact.

D. All candidate open actions must revalidate the exact managed path, ordinary-file status (no external traversal/reparse alias), file bytes and fresh SHA-256, and manifest identity. A valid receipt never authorizes a changed master. Never launch stale, tampered or different-lineage media.

E. PASS-only receipt, immutable atomic persistence, deterministic QA input identity, conflict detection and restart reconstruction depend on C010A code landing. Neither an old receipt nor a cached UI ready state counts as fresh verification. Failure must produce no PASS receipt.

F. Final media: H.264/yuv420p, profile/size/fps appropriate to current production plan, exactly one video, audio absent for fallback/overlay-only, one AAC-LC 48 kHz mono audio track for narrated master, no other streams; full decode-to-null and bounded process; real Windows C009B must preserve video packet MD5. Do not assume C009B's probe alone substitutes for final C010A full decode.

## Executable coverage matrix

Legend: **EXISTING** = upstream isolated smoke reusable (not run here); **BLOCKED** = missing landing or API; **MANUAL** = Windows application acceptance needed. Each case gets PASS/FAIL/BLOCKED/UNVERIFIED with artifact identities, test log and source SHA; never convert BLOCKED into PASS.

| ID | Scenario/input | Expected acceptance | Reuse / gate |
|---|---|---|---|
| FV-001 | N=0 O=0, ready C004, no C009 | C004 FallbackReady; C004 candidate exact; no unnecessary master creation | C004 smoke EXISTING; C009C BLOCKED |
| FV-002 | N=0 O=0, stale old C009 exists | still C004; stale master never becomes authority | C009A catalog EXISTING; C009C BLOCKED |
| FV-003 | N=1 O=0 valid WAV plan | master selected; AAC-LC 48k mono; no C004 fallback | C007B/C009B EXISTING; C009C/C010A BLOCKED |
| FV-004 | N=0 O=1 valid text overlay (captions=false) | overlay visual; byte-copy master no new audio | C008B/C009B zero-narration EXISTING; end-to-end BLOCKED |
| FV-005 | N=1 O=1 valid text overlay | overlay visual and timed AAC master; QA then single open | C007B/C008B/C009B EXISTING; end-to-end BLOCKED |
| FV-006 | captions_required=true OR captions nonempty | fail closed `FINAL_QA_CAPTION_PROFILE_UNSUPPORTED`; no ready candidate | C010A BLOCKED |
| FV-007 | missing master when N or O true | `FINAL_QA_MASTER_REQUIRED`; never C004 fallback | C010A BLOCKED |
| FV-008 | narration synthesis fails after C004 | no master ready; failed state, original C004 unchanged | C007B existing tests; coordinator BLOCKED |
| FV-009 | overlay renderer fails after C004 | no master ready; no fallback when O true | C008B existing tests; coordinator BLOCKED |
| FV-010 | FFmpeg mux fails/cancel/timeouts | bounded stop, clean partial, upstream intact, retry permitted | C009B real smoke EXISTING; integration BLOCKED |
| FV-011 | QA probe fails or full decode fails | no PASS receipt or launch | C010A BLOCKED |
| FV-012 | crash between partial output and manifest commit | restart reconciles, no partial promoted, retry / deterministic conflict | C009A smoke review; cross-process BLOCKED |
| FV-013 | crash after master but before QA receipt | restart revalidates and independently completes QA | C010A/C009C BLOCKED |
| FV-014 | restart after QA PASS | exact candidate/receipt restored only after fresh verification | C010A/C009C BLOCKED |
| FV-015 | mutate C004 bytes after planning | fail SHA/bytes verification; no master/receipt | C009A source verifier EXISTING; QA BLOCKED |
| FV-016 | mutate C007B WAV or narration manifest | fail SHA/lineage; no receipt | C009A EXISTING; C010A BLOCKED |
| FV-017 | mutate C008B MP4 or overlay manifest | fail SHA/lineage; no receipt | C008B/C009A EXISTING; C010A BLOCKED |
| FV-018 | mutate master.mp4 after QA PASS | Open rejects, never launches | C009A catalog EXISTING; C009C/C010A BLOCKED |
| FV-019 | mutate master-manifest.json or add unexpected file | reject strict managed artifact and never open | C009A catalog EXISTING; C009C BLOCKED |
| FV-020 | tamper PASS receipt/receipt digest | reject/QA failure, no launch | C010A BLOCKED |
| FV-021 | mismatch Goal/creative/production package/plan digests | refuse stale/wrong lineage even with same filename | C009A contract EXISTING; end-to-end BLOCKED |
| FV-022 | old MasterInputDigest, newer valid plan | stale master ignored or rejected, no stale receipt reuse | C009A exact lookup EXISTING; C010A BLOCKED |
| FV-023 | stale QA input digest, changed upstream manifest SHA | receipt not reusable even if MasterInputDigest unchanged | C010A BLOCKED; explicit manifest-hash nuance |
| FV-024 | conflicting receipt at same identity path | immutable conflict failure; never overwrite | C010A BLOCKED |
| FV-025 | Open: replace file between ready and click | rehash on click; refuse changed SHA/bytes | C009C BLOCKED |
| FV-026 | Open: path moved, symlink/junction or outside managed root | reject, never launch arbitrary external file | C009C/C010A BLOCKED |
| FV-027 | Open: same bytes but replaced/incorrect manifest lineage | reject; path+manifest+lineage fresh check | C009C/C010A BLOCKED |
| FV-028 | malformed ffprobe/no streams/extra stream/wrong codec, fps, dimensions, duration | fail closed, no PASS receipt | C009B probe EXISTING; final QA BLOCKED |
| FV-029 | truncated playable header but decode error late in timeline | full decode-to-null rejects | C010A BLOCKED |
| FV-030 | 832x480, 480x832, 640x640 at 24 fps | accepted only correct profile; narrated video packet MD5 equals input | C009B RealWindowsAcceptance EXISTING |
| FV-031 | wrong AAC profile/sample rate/channels, silent interval alignment | fail closed / measure timing; no PASS receipt | C009B real smoke EXISTING; final QA BLOCKED |
| FV-032 | GUI only one Open Final Video, concurrent observe/open clicks | no duplicate composition/launch or stale candidate | MANUAL; C009C BLOCKED |
| FV-033 | published Windows executable + fresh LOCALAPPDATA on real Windows | release app launches, all paths rooted locally, evidence retained | MANUAL / UNVERIFIED |
| FV-034 | cancellation, force-kill, restart with independent process PID | no zombie ffmpeg or orphan partial, correct replay | MANUAL / UNVERIFIED |
| FV-035 | missing ffmpeg/ffprobe or invalid PATH | bounded error, no network/provider fallback, no PASS receipt | C009B real smoke environment gate; C010A BLOCKED |
| FV-036 | unknown/untrusted receipt claiming PASS | never accept unbound receipt, verify digest+lineage+candidate | C010A BLOCKED |

## Existing harness — no duplicate framework

Use existing harnesses and their `Program.cs` entrypoints. Do not modify shared Desktop Core `Program.cs`. On a Windows checkout **of a deliberately integrated acceptance build**, run from repository root:

```powershell
# Windows runner      : Compile and exercise upstream smoke harness without writing production files.
dotnet run --project windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/PicotooPet.Desktop.Core.SmokeTests.csproj -c Release
dotnet run --project windows/desktop/tests/PicotooPet.CaptionOverlay.SmokeTests/PicotooPet.CaptionOverlay.SmokeTests.csproj -c Release
dotnet run --project windows/desktop/tests/PicotooPet.PostProductionMaster.SmokeTests/PicotooPet.PostProductionMaster.SmokeTests.csproj -c Release
dotnet run --project windows/desktop/tests/PicotooPet.PostProductionMasterMux.SmokeTests/PicotooPet.PostProductionMasterMux.SmokeTests.csproj -c Release
# Python contracts    : Run only existing postproduction contract tests.
python -m pytest -q tests/postproduction tests/contract/test_postproduction_master_contract.py
```

These are **commands to execute**, not claimed PASS results. C009B's real-Windows suite internally generates 24fps source, checks packet MD5 and AAC behavior, and reports UNVERIFIED when prerequisites are absent. Capture each command's exit code and named case result; test process exit 0 alone is not enough if harness emits UNVERIFIED.

## Real Windows published-build operator runbook

1. Record Windows version, .NET SDK/runtime, ffmpeg/ffprobe versions, repository SHA, published artifact SHA-256, target architecture, test timestamp, and TEMP/LOCALAPPDATA root. Use an isolated Windows test account and a test project; preserve production user data.
2. Build/package with repository-supported release scripts (`windows/desktop/scripts/Build-Phase2WindowsRelease.ps1`; inspect its parameters before invocation). Confirm actual app launches from **published output**, not only `dotnet run`. Run the four harnesses above separately, capture stdout/stderr/exit codes.
3. Create a reproducible approved production-ready goal with current creative/production package and plan. Record the exact upstream manifest SHA values, job/package/plan digests, expected runtime, source file SHA and bytes. Do not invent plans by editing durable manifests.
4. Run the four combinations FV-001/003/004/005. Distinguish **text overlays** from captions (FV-006 must reject current unsupported captions). In each case capture candidate kind, managed path, SHA/bytes, manifest SHA, C009 master identity, QA receipt identity and Open result. Require a single Goal Center Open Final Video action and no silent fallback for required postproduction.
5. For narrated versions inspect with ffprobe, decode entire video and audio to null, verify final duration/fps/stream cardinality, and compare video packet MD5 with input visual. Capture actual command lines **without** secrets or raw narration text.
6. For each negative mutation make a copy of the test user's original directory first; mutate **only disposable fixtures**. Between ready and Open alter bytes/manifest, move path, place extra entry and swap stale receipts. Each must refuse launch and must not generate/reuse a PASS receipt. Restore a clean test state using legitimate producer regeneration, never manual forged manifest repair.
7. Terminate the application process at three checkpoints (post C004/pre master, committed master/pre receipt, after receipt); restart as a new PID. Confirm durable reconciliation and no in-memory-state dependence, deleted temp debris, no unauthorized launch. Test cancellation/timeouts and verify no ffmpeg child remains.
8. Collect a redacted evidence packet per matrix ID: UTC timestamp, commit/branch, OS/app/ffmpeg versions, job and digests, exact expected/observed result, smoke log, ffprobe JSON facts summary, full-decode exit status, SHA-256 hashes before/after, state transitions and screenshot of Goal Center. Redact filesystem usernames, narration text, credentials and stderr internals.
9. Mark each ID PASS, FAIL, BLOCKED or UNVERIFIED. Release gate is **ALL required IDs PASS**, with no open safety/security blockers. G006/G007 and C010A/C009C integration must be inspected after landing before any E2E PASS claim.

## Blockers and handoff

- **B1:** C010A QA/receipt production code not present on selected baseline. Waiting for exact public entrypoint/receipt schema/durable directory and QA verification behavior. Do not invent types.
- **B2:** C009C coordinator implementation is not present on selected baseline. Waiting for Goal Center binding and Open-time revalidation flow.
- **B3:** G006/G007 documents not located in baseline tree; reconcile freeze requirements from their owning branches.
- **B4:** No real Windows execution, release-app interaction, or process restart performed by this GitHub-only preparation. All corresponding evidence remains UNVERIFIED.
- **B5:** C010A frozen v1 explicitly does **not** support true captions; overlay-only is a separate supported route. Keep FV-006 as expected rejection until scope explicitly changes.

Ownership: this document and independent scenario fixture only. No production edits, no shared harness edits, no merges/rebases/tags/releases.
