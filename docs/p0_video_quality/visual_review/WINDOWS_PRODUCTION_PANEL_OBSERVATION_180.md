# Issue 180: explicit ProductionPanel observation

This continuation uses the exact three-file permission granted in
[comment 6534058524](https://github.com/jerryjwres-hue/picotoopet-v2.0/issues/180#issuecomment-6534058524).
The preceding STOP note remains historical evidence. Work stays on the original
branch and Draft #184; no project, release builder, C011, Worker or Core API edit.

The existing ProductionPanel now has one CPU-only evidence action (the same
button cancels an active observation), an optional VLM checkbox defaulting OFF,
plain advisory status/concerns and an inline contact sheet. Nothing starts on
Loaded, refresh or job completion. Non-completed Jobs cannot invoke it; an exact
three-shot context must still be verified before the read-consent dialog.

The wrapper reads only the existing exact Job, Plan and Production Package APIs.
It validates the canonical frozen plan digest, matching package/creative/job
identity and opaque package ZIP digest, and joins three unique task/shot outputs
to plan order. The package digest is never falsely recomputed as a JSON hash.
The fact snapshot is checked again after consent and after CLI completion.

Only `ComfyUI/config.json`'s explicit local `basePath/output` is eligible: no
fallback candidates, filename guesses or media search. The dialog identifies all
three paths, IDs, sizes and SHA256 values. Only after read consent does the wrapper
pin each ordinary local NTFS source/namespace, check EBML/bytes/SHA256 and retain
read-only handles through CLI completion and rechecks. User cancellation/timeout
kills only the created child tree before releasing its file/tool leases.

The reviewer remains `tools/p0_visual_review`. The wrapper supplies its existing
manifest/arguments and validates the returned nine frames, exact sampler
timecodes, IDs, source hashes, PNG hashes and contact sheet before display.
The CLI receives small defensive changes only: explicit local Matroska/software
decoding, file/pipe protocol allowlist, strict model response fields/frame order
and a required completed-inference indicator. No new sampling or VLM engine.

Legacy `ADVISORY_REVIEW` becomes UI `REVIEW`; the other outcomes are
`REJECT_SUSPECT` and `UNVERIFIED`. Disagreement, low confidence or evident injected
instructions cannot strengthen the verdict. Text is plain, not commands/markup.
No AI result becomes human ACCEPT, a C011 receipt, a production state change or a
rerender. Evidence/input/provenance files are separate, non-authoritative review
material. Installed/model-inference claims come from the existing CLI protocol;
persistent loading and perceptual accuracy remain unverified.

## Deployment is still an explicit unmet condition

The default runtime accepts only the fixed application-relative directory
`tools/p0_visual_review`, with an application-embedded approved pin resource:
`PicotooPet.Desktop.Services.QualityObservation.ObserverDeployment`, string
`Receipt`. It does not trust a replaceable sidecar, PATH lookup, Core-provided
executable, arbitrary command, `dotnet` invocation or runtime download.

The receipt schema is `visual_review.deployment.v1`: a 64-hex source-content
SHA256, `self_contained_single_file=true`, exactly the approved observer EXE,
ffmpeg.exe and ffprobe.exe names/bytes/SHA256, and optionally a separately approved
private IPv4/model configuration. Binary and namespace pins persist through use.
The resource must come from an independently approved prebuilt package, not
self-declared tool output. **No such resource or deployed package is provided by
this change.** Absence, modification or missing tools returns UNVERIFIED.
No installation, packaging, signing, csproj or official release changes were made.

Optional VLM needs BOTH a configured private-LAN model and a second explicit
three-frame-transfer consent; read consent alone never sends images. No current
task operation contacts a model, probes a LAN or downloads/loads model weights.
Actual device deployment remains BLOCKED pending the approved binary pins/package
and the owner's verified local output configuration.

## Session safety limitation

The allowed public session API exposes no credential generation. Same-address
re-pairing may remain Online, so the adapter conservatively invalidates on **every
SnapshotChanged notification**, including identical snapshots. This fences the
supported pairing path and prevents stale selection/session results. Unrelated
task or latency snapshots can therefore cancel an in-flight review or clear a
displayed result. This is a real usability limitation; native synthetic PASS does
not prove acceptable live-session behavior. A precise credential-generation hook
would require a separate narrow session-owner authorization, not private reflection
or an unapproved credential read in this adapter.

## Native tests and real-media acceptance

New test-only registration follows the repository's ModuleInitializer smoke
pattern. Only on a GitHub Windows runner it builds a disposable WPF test project
in RUNNER_TEMP using a text fixture and a reference to the real Desktop project.
Existing test/project/workflow files are not edited; no SDK command runs from the
production action or on an operator device. The existing quality native CI runs
the WPF contracts before its existing CPU FFmpeg synthetic-grid/tamper cases.

Contracts cover missing/tampered sources, wrong Job/Plan/Package/task/shot,
traversal, malformed/misbound/tampered reports, exact read consent, VLM-off and
separate transfer consent, uncertain/injected mock output, cancellation, stale
selection, identical Online session notifications and actual WPF button binding.
No mock tests certify real cats, clothing, floating lamps, product shape, scene
continuity, causal story or first-pass usable yield. Windows quality and WPF/Control
run IDs on the exact source SHA must be checked before claiming native UI PASS.

After a separately approved prebuilt deployment and stable source context, the
single operator step is to select the completed three-shot Job, click the CPU
observation action and consent to the displayed exact three WebMs. Leave VLM OFF
unless its separate transfer/resource authorization is explicitly provided.
The original job `64695948-fb1a-4793-815f-3f6ad4d4d536` remains human
VISUAL_REJECT. Its actual media and read permission were not obtained or used;
calibration, live UX, visual accuracy and quality-yield improvement remain UNVERIFIED.
