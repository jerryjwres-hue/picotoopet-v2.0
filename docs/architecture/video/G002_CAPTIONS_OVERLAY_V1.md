# G002 — Captions & Text Overlay v1 Architecture

Status: docs-only architecture design for C008.  
Branch: `design/captions-overlay-v1`.

This document defines an implementation-ready boundary for deterministic captions and text overlays without changing C006A `TEXT_CARD` semantics or C004 final assembly.

## 1. Scope and non-goals

C008 owns **post-production text presentation over an already-rendered video timeline**.

It does not own:
- Creative generation.
- Production shot generation.
- C006A `TEXT_CARD` rendering.
- C007A narration planning or TTS.
- C004 shot concatenation/final-video assembly.
- arbitrary compositor graphs, fonts, models, providers, endpoints, commands, or paths.
- AI rewriting, caption invention, summarization, or translation.

The architecture must keep these three concepts separate:

| Concept | Meaning | Timing unit | Produces/replaces a full shot? | C008 authority |
|---|---|---|---:|---:|
| `TEXT_CARD` | A full visual card/shot selected by Creative render intent and rendered through Production | Production task / shot | Yes | No |
| caption | Timed subtitle/lower-third representing narration/speech | caption cue | No | Yes, when a trusted narration text/transcript source exists |
| overlay/title | Explicit authored on-screen title/callout over existing video | beat-derived overlay cue | No | Yes |

A caption or overlay is never converted into `TEXT_CARD`, and `TEXT_CARD` is never treated as a caption or overlay.

## 2. Repository facts audited

The design was checked against the current real repository, including separate in-flight branches rather than assuming they were already merged.

### 2.1 Creative contracts

Current `src/picotoopet_core/creative/models.py` defines:
- `ScriptBeat.voiceover`
- `ScriptBeat.on_screen_text`
- `ShotPlanItem.text_reference`
- `ShotPlanItem.render_intent`
- `CreativeRenderIntent.TEXT_CARD`

Important semantic boundary:
- `on_screen_text` is beat-level explicit authored visual text.
- `text_reference` is shot-level renderer-facing text reference.
- neither field grants command/filter/font/path authority.

### 2.2 C005 timeline/output profiles

Audited branch:
- `feature/video-timeline-output-profiles`
- HEAD at audit: `e82df96a7acddfb7cc2b26c023517b58716b226b`

C005 establishes:
- `ProductionPlan.output_profile_id`
- `ProductionPlan.target_runtime_ms`
- ordered `ProductionTaskPlan` entries
- per-task `target_duration_ms`
- frozen width/height/fps from a closed `VideoOutputProfile`
- deterministic ordering and runtime validation

For C008, **ProductionPlan task durations are the timeline authority**. Creative floating-point durations are descriptive source facts, not rendering-clock authority after ProductionPlan exists.

### 2.3 C007A narration plan

Audited branch:
- `feature/narration-plan-core-v1`
- HEAD at audit: `4f7d6e075ff88e1e939b62ef29994c2b5a0de8bf`

Current `NarrationPlanV1`:
- is derived read-only from Creative Package + frozen ProductionPlan
- carries `production_plan_digest`
- carries `target_runtime_ms`
- maps voiced beats to ordered non-overlapping `start_ms/end_ms` windows
- carries bounded narration text + per-segment text digest
- has a canonical `narration_plan_digest`
- does not mutate Production

C007A is a **planning contract**, not a generated-audio transcript artifact. C008 must not relabel planned voiceover text as a measured transcript without an explicit future transcript contract.

### 2.4 C006A TEXT_CARD contract

Audited branch:
- `feature/render-intent-text-card-v1`
- HEAD at audit: `aa7976bbc2739b329021ec7fa760c301ec58c057`

C006A's locked semantic intent is:
- `TEXT_CARD` becomes an ordinary executable Production task using a local-media backend.
- preferred card text source is `ShotPlanItem.text_reference`, then matching `ScriptBeat.on_screen_text`.
- the renderer emits a normal timeline-compatible `video/webm`.
- the output enters the existing Production Package.
- C004 consumes it as a normal ordered shot.

Therefore C008 must never implement `TEXT_CARD` by drawing text over the assembled video.

### 2.5 C004 final assembly and Windows media boundary

Audited branch:
- `feature/goal-final-video-assembly`
- HEAD at audit: `866af949a1c7d180a867cabf17b6bcb669b856f9`

Current C004:
- verifies ordered Production Package outputs
- resolves only managed relative source paths
- rejects traversal/rooted paths and reparse/symlink escape
- recomputes SHA-256
- uses fixed `ffmpeg.exe`
- uses `ProcessStartInfo.ArgumentList`, no shell
- builds internal FFmpeg arguments
- writes a managed MP4 plus a bounded local final-video manifest
- reuses a matching verified artifact after restart
- fails closed on conflicts

`ProductionLocalEnvironment` already provides reusable managed-root/path/hash primitives.

C008 must reuse this style of security boundary but **must not modify C004**.

## 3. Architecture decision

Use one root contract with two strictly separate cue collections:

- `CaptionOverlayPlanV1`
  - `captions: list[CaptionCueV1]`
  - `overlays: list[TextOverlayCueV1]`

This keeps provenance/digest/restart behavior in one bounded post-production plan while preserving caption-vs-overlay semantics in distinct models.

The plan is a Core-authored read-only derivative. Rendering remains a Windows local derived artifact.

### 3.1 Root contract

Required bounded fields:

- `schema_version = "1.0"`
- `production_job_id`
- `creative_package_id`
- `creative_package_digest`
- `production_plan_digest`
- `narration_plan_digest: str | null`
- `output_profile_id`
- `target_runtime_ms`
- `render_profile_id = "postproduction.text-burnin.windows.v1"`
- `font_profile_id = "font.windows-system-sans.v1"`
- `captions_required: bool`
- `overlays_required: bool`
- `captions`
- `overlays`

The contract is `extra="forbid"` and frozen.

It must not contain:
- executable path
- font path
- filter graph/filter string
- provider/model/workflow IDs
- arbitrary width/height/fps
- arbitrary output path
- shell command
- HTML/CSS
- ASS/SSA control markup
- raw Creative Package JSON

Width/height/fps are resolved from the closed C005 `output_profile_id`, not supplied by C008 payload fields.

### 3.2 Caption cue contract

`CaptionCueV1` fields:

- `cue_id` — stable deterministic ID
- `order`
- `beat_id`
- `text`
- `text_sha256`
- `start_ms`
- `end_ms`
- `source_kind` — closed enum
- `style_profile_id = "caption.lower-third.v1"`

Allowed source kinds:
- future `narration_transcript.v1`
- optionally a separately approved future `narration_plan_text.v1` mode if product explicitly chooses planned subtitles

For the current repository baseline, C007A does **not** provide a transcript artifact. Therefore the default C008 v1 planner must not claim transcript-grade captions from C007A alone.

### 3.3 Text overlay cue contract

`TextOverlayCueV1` fields:

- `cue_id`
- `order`
- `beat_id`
- `text`
- `text_sha256`
- `start_ms`
- `end_ms`
- `source_kind = "script.on_screen_text"`
- `style_profile_id = "overlay.title-safe.v1"`

No per-cue x/y/font/size/color/filter parameters are accepted.

## 4. Text-source policy

C008 has no generative text step.

### 4.1 Overlay/title source

Only nonblank `ScriptBeat.on_screen_text` may authorize a v1 overlay/title.

`ShotPlanItem.text_reference` is intentionally **not** an overlay source. It exists in the shot/render-intent domain and is already consumed by C006A for `TEXT_CARD`.

This is the key semantic firewall that prevents card text from silently becoming a second post-production overlay.

### 4.2 Caption source

Captions are speech/narration text, not `on_screen_text`.

Source order for the caption domain is:
1. a future trusted narration transcript contract tied to C007 rendered narration/audio
2. no caption cue

No AI invention, paraphrase, translation, ASR call, or fallback to unrelated Creative fields is allowed in v1.

C007A `NarrationPlanV1` remains useful now for:
- production/narration identity binding
- beat windows
- narration plan digest
- future transcript alignment

but it is not silently promoted to a transcript.

### 4.3 Source coexistence

If a beat has both an overlay and a caption:
- both remain separate cues
- neither replaces the other
- the renderer uses separate frozen style zones
- overlap is solved by style geometry, not by dropping text

This is not a single "best text" stream.

## 5. Timing authority and beat/shot mapping

### 5.1 Clock authority

C008 must derive all windows from ordered `ProductionPlan.tasks[*].target_duration_ms`.

It must verify:
- task order is exactly consecutive
- task shot IDs exactly match the Creative ShotPlan
- every shot resolves to a known beat
- beat ordering does not move backward
- a beat is not reopened after another beat has begun
- accumulated task duration equals `ProductionPlan.target_runtime_ms`

These are the same core timeline invariants already enforced by C007A narration planning.

C008 must not import or call C007A's private `_beat_windows` helper. C008 may implement an equivalent bounded helper in its own module and test parity. A later cleanup may move both to a public shared post-production timeline utility, but G002/C008 must not modify C007A to achieve that.

### 5.2 Overlay windows

`on_screen_text` is beat-level, so an overlay normally spans the full contiguous Production window for that beat.

No word-level or animation timing is inferred.

### 5.3 Caption windows

A future transcript contract must provide bounded cues tied to the same Production/Narration identity.

If the future transcript is only beat-granular, its cue window may use the corresponding C007A beat window.

If it later becomes word/phrase granular, C008 may accept those timings only through a new schema version or explicitly versioned transcript contract. V1 must not guess word timing.

## 6. TEXT_CARD collision policy

Because C006A can use `on_screen_text` as fallback card text, blindly burning the same beat text after assembly can duplicate content.

V1 rule:

- caption cues may coexist with `TEXT_CARD` because captions represent narration/speech.
- overlay/title cues must not overlap a Production task whose `render_intent == TEXT_CARD`.
- if explicit `on_screen_text` maps to a beat containing any `TEXT_CARD` task, planning fails closed with a bounded ambiguity code rather than silently duplicating, suppressing, or reinterpreting the text.

Recommended code:
- `TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS`

This is intentionally conservative. A future Creative schema may add explicit overlay-vs-card placement intent; v1 will not infer it.

## 7. Closed style profiles

V1 allowlist:

- caption: `caption.lower-third.v1`
- overlay/title: `overlay.title-safe.v1`

Style definitions live in source-controlled Windows code/resources and are selected only by these logical IDs.

A style profile may internally define:
- alignment
- margins
- font size relative to known output profile
- line-wrap policy
- maximum lines
- outline/shadow
- safe-area geometry

The plan must never carry these raw renderer parameters.

### 7.1 Output-profile aware geometry

The renderer resolves style geometry from C005:
- landscape `832x480 @ 24`
- vertical `480x832 @ 24`
- square `640x640 @ 24`

A closed mapping may vary font size/margins by output profile while keeping the same logical style ID.

## 8. Font policy

V1 plan carries only:
- `font_profile_id = "font.windows-system-sans.v1"`

It does not carry:
- font file path
- arbitrary family name
- URL
- downloaded font
- user-selected font

Windows maps the logical profile to a source-controlled closed family policy.

Initial policy:
- use an approved Windows system sans family selected by renderer code
- no payload/config override
- no FFmpeg `fontsdir` authority
- no arbitrary font discovery path

If real-machine glyph coverage is insufficient for a required string, fail with a bounded rendering error rather than downloading or selecting an arbitrary font.

A future bundled-font profile requires a separately reviewed asset/licensing/deployment slice.

## 9. Rendering decision: burned-in v1

### 9.1 Decision

V1 output is **burned-in text** over the C004 final MP4.

Do not choose a sidecar subtitle track as the primary v1 output.

Reason:
- sidecars can model captions but not the full overlay/title requirement consistently
- product behavior must be visible in ordinary Windows playback without player subtitle configuration
- a single burn-in renderer can render both distinct cue types with frozen styles
- C004 stays unchanged because burn-in is a separate downstream derived artifact

### 9.2 C004 remains untouched

C008 does not add filters or text handling to `FinalVideoAssemblyService`.

Windows flow is:

`Production Package -> C004 verified final MP4 -> C008 verified text burn-in MP4`

C008 may depend on the public C004 assembler/artifact abstraction after C004 lands, but it must not change C004 behavior, manifest schema, output naming, or source verification.

### 9.3 Sidecar future

The timed caption plan is sufficient to export WebVTT/SRT later.

Sidecar export is not a v1 rendering requirement and must not become a second timing/source authority.

## 10. Windows deterministic rendering boundary

Recommended new Windows service:
- `PostProductionTextRenderService`

Recommended internal renderer:
- `FixedTextBurnInFfmpeg`

The service should reuse:
- `ProductionLocalEnvironment`
- the C004 fixed `ffmpeg.exe` / no-shell process discipline
- managed-root resolution
- ordinary-file checks
- SHA-256 verification
- bounded timeout/failure mapping

### 10.1 Source video authority

C008 must not accept an arbitrary input video path from Core, user input, config, or a Goal payload.

The source must be a verified C004 `FinalVideoArtifact` obtained from the C004 service for the exact `production_job_id`.

Before rendering, C008 verifies:
- production job identity
- source file remains an ordinary managed file
- source hash matches C004 artifact/manifest facts
- source is inside the managed final-video root
- no reparse/symlink escape

### 10.2 ASS event generation

Preferred v1 mechanism is an internally generated managed ASS/SSA document because it supports:
- deterministic timed events
- separate fixed caption/overlay styles
- line wrapping
- safe-area placement
- Unicode text

The ASS document is an internal renderer artifact, not an externally supplied contract.

Security rules:
- text is escaped as data; it cannot inject ASS override tags
- braces/backslashes/newlines are normalized/escaped by renderer-owned code
- style names are renderer constants
- PlayResX/PlayResY come from C005 profile
- no user-authored ASS markup
- no external style file
- no arbitrary filter graph

FFmpeg invocation remains internally authored and uses:
- fixed `ffmpeg.exe`
- no shell
- fixed H.264/yuv420p MP4 output policy compatible with C004
- fixed text/subtitle filter construction referencing only the managed internal ASS file
- no arbitrary command/filter options from the plan

### 10.3 Output location

Recommended managed root:

`%LOCALAPPDATA%\PicotooPet\PostProduction\TextV1`

Output filename identity is derived only from trusted identities, e.g.:
- hash of `production_job_id`
- prefix of `caption_overlay_plan_digest`

No user text appears in filenames.

Partial files use a temporary managed name and are atomically renamed only after successful verification.

## 11. Provenance, digest, and restart reuse

### 11.1 Plan digest

`caption_overlay_plan_digest` is canonical SHA-256 over the complete validated plan:
- UTF-8
- sorted keys
- compact separators
- no timestamps

Any change in:
- Creative package digest
- Production plan digest
- narration/transcript digest
- cue text/timing
- style/font/render profile
- required/optional policy

must change the plan digest.

### 11.2 Local rendered artifact manifest

C008 writes a bounded local manifest beside the burned-in MP4 containing only:
- schema version
- production job ID
- C004 source final-video SHA-256
- caption/overlay plan digest
- renderer profile ID
- ordered caption text digests
- ordered overlay text digests
- final filename
- final SHA-256
- final bytes
- created_at

Do not persist:
- absolute source paths
- raw Creative manifest
- raw transcript package
- commands/filter graphs
- credentials
- arbitrary environment details

### 11.3 Restart behavior

For the same verified C004 source hash + same plan digest:
- verify existing output and manifest
- reuse without rerender

If only one of output/manifest exists, or provenance/hash does not match:
- fail closed with artifact conflict
- do not overwrite silently

A changed plan digest gets a different deterministic output identity rather than overwriting an older valid variant.

## 12. Required vs optional failure behavior

V1 default policy:

- `overlays_required = true` when any explicit `on_screen_text` exists
- `captions_required = false` until a product-level closed caption requirement is introduced

Consequences:

### 12.1 Required overlays

If explicit `on_screen_text` exists and cannot be mapped/rendered deterministically:
- fail C008 planning/rendering
- do not silently omit authored on-screen text

Examples:
- timeline ambiguity
- `TEXT_CARD` overlap ambiguity
- unsupported glyph under the frozen font policy
- renderer failure

### 12.2 Optional captions

If no trusted transcript exists:
- plan may contain `captions=[]`
- overlays can still proceed
- absence is not a failure

If a later closed policy sets `captions_required=true`:
- missing transcript becomes bounded `not ready`, preferably HTTP 409 at the Core read-only plan layer
- rendering never invents caption text

## 13. Failure codes

Recommended Core planning codes:
- `TEXT_PRESENTATION_NOT_READY`
- `TEXT_PRESENTATION_SOURCE_MISMATCH`
- `TEXT_PRESENTATION_TIMELINE_AMBIGUOUS`
- `TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS`
- `TEXT_PRESENTATION_PROFILE_UNSUPPORTED`
- `TEXT_PRESENTATION_CAPTION_SOURCE_MISSING`

Recommended Windows rendering codes:
- `TEXT_BURNIN_SOURCE_INVALID`
- `TEXT_BURNIN_SOURCE_HASH_MISMATCH`
- `TEXT_BURNIN_GLYPH_UNSUPPORTED`
- `TEXT_BURNIN_FFMPEG_UNAVAILABLE`
- `TEXT_BURNIN_FFMPEG_FAILED`
- `TEXT_BURNIN_FFMPEG_TIMEOUT`
- `TEXT_BURNIN_OUTPUT_INVALID`
- `TEXT_BURNIN_ARTIFACT_CONFLICT`

Errors must not include:
- caption/overlay text
- absolute paths
- raw FFmpeg stderr
- raw manifest content

## 14. Core service/API boundary

Recommended pure compiler signature conceptually consumes:
- frozen `ProductionPlan`
- `production_plan_digest`
- Creative Package manifest + digest
- optional trusted narration/transcript facts

It returns:
- validated `CaptionOverlayPlanV1`
- canonical plan digest

Recommended service remains read-only over existing repositories, like C007A.

Do not add a new Core DB table for v1.

### 14.1 API ownership

To avoid modifying C007A during parallel work, the first C008 implementation slice should be **compiler + tests only**.

A later integration slice may add a dedicated route module rather than editing C007A's route implementation in-place.

Suggested endpoint when integration is allowed:

`GET /postproduction/production/{production_job_id}/caption-overlay-plan`

The endpoint returns a plan, never renderer commands or local Windows paths.

## 15. Interaction with future C009 compositor

C008 must expose a stable text-presentation plan, not hide semantics inside FFmpeg arguments.

C009 may later:
- consume the C008 plan directly as a visual text layer
- consume C007 narration/audio as an audio layer
- compose both in one final transcode

When C009 exists, it may bypass the standalone C008 burn-in artifact to avoid an extra transcode, but it must preserve:
- C008 cue semantics
- C008 plan digest/provenance
- closed styles/font policy
- timing authority

C009 must not require changing C004 into a compositor.

C004 remains the verified ordered shot assembler.

## 16. Accessibility/export implications

Burned-in captions are visible in ordinary playback but are not:
- selectable
- disable-able
- exposed as a native subtitle track

V1 accepts that limitation.

The structured caption cue contract deliberately preserves:
- text
- timestamps
- source provenance

so a future WebVTT/SRT/native subtitle export can be added without re-running AI or changing timing authority.

No accessibility-specific second text source is introduced in v1.

## 17. Likely implementation files

### C008A — Core plan compiler

Preferred new files after C007A is available in the integration base:
- `src/picotoopet_core/postproduction/captions_overlay.py`
- `tests/postproduction/test_captions_overlay_plan.py`

Optional later route integration:
- `src/picotoopet_core/api/routes/captions_overlay.py`
- minimal router registration in `src/picotoopet_core/api/app.py` only after current parallel owners are clear

Avoid changing C007A's narration module.

### C008B — Windows burned-in renderer

Preferred new files:
- `windows/desktop/src/PicotooPet.Desktop/Services/PostProductionTextRenderService.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/FixedTextBurnInFfmpeg.cs`
- focused smoke test files under `windows/desktop/tests/PicotooPet.Desktop.Core.SmokeTests/`

Reuse public C004/C005 helpers after they land. Do not fold C008 logic into `FinalVideoAssemblyService.cs`.

## 18. Forbidden files / ownership boundaries

G002 docs task must not modify implementation files.

C008 implementation must not modify, during the current parallel ownership window:

### C006A-owned / TEXT_CARD
- `src/picotoopet_core/production/models.py`
- `src/picotoopet_core/production/profile.py`
- `src/picotoopet_core/production/compiler.py`
- `src/picotoopet_core/production/package.py`
- C006A Windows local-media/TEXT_CARD renderer files
- C006A focused tests

### C007A-owned
- `src/picotoopet_core/postproduction/narration.py`
- `src/picotoopet_core/api/routes/postproduction.py`
- `tests/postproduction/test_narration_plan.py`
- any C007A task/contract file

### C004-owned
- `windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoAssemblyService.cs`
- `windows/desktop/src/PicotooPet.Desktop/Services/GoalFinalVideoCoordinator.cs`
- `windows/desktop/src/PicotooPet.Desktop/ViewModels/GoalVideoContinuationViewModel.cs`
- C004 final-video manifest/assembly tests

Also do not modify:
- S002 Production HTTP connection-lifecycle files
- Maotai/Natural Motion/UI work
- deploy/release/tagging surfaces

If a future integration needs a currently owned shared file, wait for that owner to land and perform the change in a later integration slice.

## 19. Test plan

### 19.1 Core compiler tests

Must cover:
1. no `on_screen_text` + no transcript => valid empty plan
2. one overlay beat => exact ProductionPlan window
3. multi-shot beat => one contiguous overlay window
4. cumulative multi-beat timing
5. `on_screen_text` never becomes a caption
6. narration/transcript caption never becomes an overlay/title
7. `ShotPlan.text_reference` alone creates no caption/overlay
8. `TEXT_CARD` + `on_screen_text` overlap => bounded ambiguity failure
9. caption over `TEXT_CARD` remains semantically allowed
10. unknown shot/beat => timeline ambiguity
11. non-contiguous reopened beat => timeline ambiguity
12. task order inversion/mismatch => timeline ambiguity
13. production runtime mismatch => failure
14. identity/digest mismatch => source mismatch
15. unknown style/font/render profile => rejected
16. extra provider/model/path/filter/font-path/command fields => rejected
17. same inputs => same complete plan + digest
18. changed ProductionPlan/narration/transcript digest => changed plan digest
19. errors do not leak text
20. required overlay cannot be silently dropped
21. optional caption absence is non-fatal
22. required-caption mode without transcript => not-ready

### 19.2 Windows renderer tests

Must cover:
1. source comes only from verified C004 artifact path/identity
2. traversal/rooted/reparse source rejected
3. source hash mismatch rejected
4. fixed `ffmpeg.exe`
5. no shell
6. fixed internally-authored filter strategy
7. no arbitrary font path/family from plan
8. ASS text escaping blocks style/control injection
9. caption and overlay map to distinct frozen styles
10. C005 width/height/fps preserved
11. source C004 MP4 is never modified/deleted
12. partial output never becomes durable success
13. timeout/nonzero exit maps to bounded codes
14. output is verified before atomic promotion
15. same source hash + same plan digest reuses artifact
16. tampered/mismatched output or manifest fails closed
17. manifest contains no absolute path/raw text/command
18. exception/status text contains no user caption/overlay content

### 19.3 Regression

When C008B integrates:
- existing C004 assembly tests remain unchanged and pass
- existing C005 Production tests pass
- C006A TEXT_CARD tests pass unchanged
- C007A narration tests pass unchanged
- Windows solution/build and Control Center CI pass

## 20. Acceptance criteria

C008 v1 is accepted when:

1. The system can deterministically derive a bounded overlay plan from explicit `on_screen_text` using C005 timing.
2. Caption cues can only come from an explicitly trusted narration transcript/source contract; no AI invention occurs.
3. `TEXT_CARD`, caption, and overlay/title remain separate semantic domains.
4. `text_reference` does not become post-production text authority.
5. `TEXT_CARD`/overlay ambiguity fails closed.
6. The plan contains no arbitrary renderer authority.
7. Windows can burn the validated plan over the verified C004 artifact using a fixed local FFmpeg boundary.
8. C004 itself is unchanged.
9. Same source + plan can be safely reused after restart.
10. Provenance is bounded and digest-linked.
11. Optional captions can be absent without dropping required authored overlays.
12. Future C009 can consume the plan without changing C004 or reinterpreting text semantics.

## 21. Implementation slices and agent recommendation

### Slice 1 — C008A Core plan compiler

Owner recommendation: GPT/Codex-like agent focused on Python contracts and deterministic tests.

Scope:
- new plan/cue models
- pure compiler
- digest
- timing/source/`TEXT_CARD` collision validation
- tests only

Do not add API routing in this first slice. This avoids C007A route/app ownership conflict.

### Slice 2 — C008B Windows renderer

Owner recommendation: Codex-like agent after C004 is integrated.

Scope:
- new standalone text-burn-in service
- fixed ASS generation
- fixed FFmpeg execution
- managed artifact manifest/reuse
- smoke tests

Do not modify C004.

### Slice 3 — integration

After current owners land:
- read-only Core endpoint
- Windows client/coordinator wiring
- product status/UI integration if separately assigned
- later C009 handoff

## 22. Current blockers and sequencing

Architecture blocker: none.

Implementation sequencing constraints:
- C008A should be based on a tree where C005 is present and C007A's public post-production package exists, or it should add only its own new module/test without editing C007A-owned files.
- C008B should wait until C004 public final-video artifact/service and shared path helpers are available in the integration base.
- C006A implementation is not required for C008A compiler work, but its locked `TEXT_CARD` semantics must remain unchanged.
- real Windows acceptance must confirm the installed `ffmpeg.exe` supports the chosen ASS/subtitle filter and the frozen font policy covers required glyphs. Failure of that probe must fail closed; it must not broaden to arbitrary fonts/filters.

READY_TO_IMPLEMENT: yes

NEXT IMPLEMENTATION SLICE: C008A — Core-only `CaptionOverlayPlanV1` compiler + canonical digest + deterministic timing/source/TEXT_CARD-collision tests. Add only new C008 module/test files; do not edit C006A/C007A/C004.

BLOCKERS: No architecture blocker. C008B Windows burn-in integration is sequenced behind C004 availability in the integration base; caption population beyond overlays is sequenced behind an explicit trusted narration transcript/source contract. Real Windows FFmpeg ASS/filter and glyph coverage require acceptance validation.

FILES OWNERSHIP: G002 docs owns only `docs/architecture/video/G002_CAPTIONS_OVERLAY_V1.md`. C008A should own new `src/picotoopet_core/postproduction/captions_overlay.py` and `tests/postproduction/test_captions_overlay_plan.py` only. C006A Production/TEXT_CARD files, C007A narration/postproduction route/tests, and C004 final-assembly/Goal files remain forbidden.
