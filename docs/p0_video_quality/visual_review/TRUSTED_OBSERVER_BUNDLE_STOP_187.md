# Issue #187: approved offline observer input required

Status: STOP at binary supply/approval; no production change. Branch:
`feature/p0q2-win-trusted-observer-bundle-20261102`.
Inspected frozen source: `23d067cf84dba4dda9b130272b2c098f2b0e6d24`.

## Evidence and authority

Issue #187 requires specifically approved credible provenance and independently
approved hashes/bytes before packaging real Windows FFmpeg/FFprobe. No approval,
Windows binary supply, approved release URL/version, or immutable checksums were
provided in the issue or repository. No download has been attempted.

`DeployedVisualObservationRuntime.OpenDeployment` reads only the Desktop assembly
resource `PicotooPet.Desktop.Services.QualityObservation.ObserverDeployment`, string
`Receipt`. That resource is absent. It checks exactly three names/lengths/SHA256s,
local NTFS namespace pins and file leases. The checks remain unchanged; missing
resource yields `OBSERVER_NOT_DEPLOYED`, displayed as `UNVERIFIED`.

Inspected `PicotooPet.Desktop.csproj`: no observer resource or three-tool publish
content. Inspected `Build-Phase2WindowsRelease.ps1`: it publishes the Desktop and
diagnostics, tests them and inventories payload files into the release manifest;
it neither builds nor supplies the visual observer trio. Its unsigned CI manifest
records build provenance, not independent approval of third-party executable
bytes. Existing asset/release gates do not supply such approval either.

`tools/p0_visual_review/PicotooPet.VisualReview.csproj` supplies the existing .NET
CLI source, not preapproved self-contained Windows bytes. The visual native
workflow resolves FFmpeg via PATH/Chocolatey for synthetic CI media. That test
convenience is not approval to redistribute those executables, and its output must
not be promoted to production pins. No workflow was edited, including #186's
`windows-ui-preview-release.yml`.

## Exact owner-supplied input

Provide an immutable offline input bundle in a controlled build environment, plus
an independently reviewable owner approval identifying its digest and contents.
This is a supply checklist, not a new runtime manifest or trust authority:

- Exact `win-x64` `PicotooPet.VisualReview.exe`, `ffmpeg.exe`, `ffprobe.exe` bytes;
  no renamed scripts, synthetic substitutes or extra executable dependencies.
- For each executable: positive exact byte length and lowercase 64-hex SHA256,
  independently confirmed against the approved bytes. For an input archive, also
  identify its exact name, length, SHA256 and the three exact member paths.
- FFmpeg/FFprobe: specifically approved publisher and immutable version/build,
  original upstream/release URL, source revision and build/configuration provenance,
  checksum/signature verification evidence where published, and redistribution
  license/notices. Confirm that the pair is self-contained for the intended runner
  and installed environment; external DLL/runtime requirements need review.
- Observer: source commit and unambiguous source-content SHA256 (a Git SHA1 is not
  this field), exact approved source inventory/digest recipe, SDK version and
  publish flags, native build Run ID/artifact digest. Publish the existing CLI as
  `win-x64`, self-contained single-file, untrimmed. Owner approval must bind these
  actual output bytes, not merely authorize a future self-asserted hash.
- Approval reference: owner/controller identity and immutable issue/comment or
  approved review identifying exactly these digests, provenance and redistribution
  scope. An agent-generated checksum alone is not independent approval.

The existing embedded Receipt must contain the following exact JSON keys (the
parser uses snake_case and rejects unmapped members). This is deliberately a
non-executable template; placeholders are not hashes or approved values:

```text
{
  "schema_version": "visual_review.deployment.v1",
  "source_sha256": "<approved observer source-content SHA256>",
  "self_contained_single_file": true,
  "files": [
    {"name":"PicotooPet.VisualReview.exe","sha256":"<approved SHA256>","bytes":<approved integer>},
    {"name":"ffmpeg.exe","sha256":"<approved SHA256>","bytes":<approved integer>},
    {"name":"ffprobe.exe","sha256":"<approved SHA256>","bytes":<approved integer>}
  ],
  "vlm_endpoint": null,
  "vlm_model": null
}
```

Provenance/approval records are reviewed build inputs; do not add their fields to
the runtime Receipt or trust a replaceable sidecar. VLM stays off; no network/model
configuration is necessary to ship the CPU evidence path.

## Shortest integration after approval (not implemented)

1. Validate supplied bytes against independently approved pins without executing
   unknown inputs. Publish the existing observer on a native Windows runner only
   if that build/output approval route was explicitly selected by the owner.
2. Embed the approved Receipt as `ObserverDeployment.resx`/`Receipt` under the
   existing QualityObservation resource namespace. Use only the narrowly approved
   csproj/builder extension to include the approved three bytes at
   `<Desktop directory>/tools/p0_visual_review/`. Copy unchanged and verify hashes
   before and after publish. Do not derive approval from arbitrary input paths,
   ENV/PATH, tool stdout or the release manifest generated by the same build.
3. In disposable native CI, publish the Desktop with the approved fixture bundle;
   exercise its actual embedded resource and `OpenDeployment`, then missing,
   altered, misbound and unsafe namespace negatives. Fixtures remain test-only;
   their success is not a shippable approval. Retain real source pinning, consent,
   manual CPU-only invocation and cancellation tests. Require Visual, Control,
   Same-EXE and C011 results on the same final SHA. No new QA engine/workflow.
4. Preserve the existing install/verify/rollback and Full/Maotai gates. If integration
   needs any installer, verifier or workflow change, STOP for exact authorization.

## Separate acceptance states

- `SOURCE_WIRED`: existing #184 implementation is present; this change only records
  the supply blocker and does not introduce a new source implementation PASS.
- `DEPLOYABLE_WITH_APPROVED_PINS`: **BLOCKED**; no approved trio or embedded Receipt.
- `REAL_MEDIA_VISUAL_ACCURACY`: **UNVERIFIED**; no real videos or user device accessed.
  The human-rejected cat/scarf job remains VISUAL_REJECT. CPU grids do not prove
  perceptual quality, narrative causality, AI calibration or usable-yield gains.

No fake positive tests are added for this supply blocker. Native CI for this
commit, if run, is regression evidence only; it cannot establish deployability.
No models, GPU, Core/Comfy calls, Worker/C011/authorization or Maotai changes.
