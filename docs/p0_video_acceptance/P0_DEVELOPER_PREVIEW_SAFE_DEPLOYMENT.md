# P0 Developer Preview — READ BEFORE INSTALLING

NOT a formal Release. Application source is frozen at
`9b6faec72dfba7da0db31fcd2cbce5388480bb88` (Draft #117), product version `2.3.27.1`.
The independent workflow commit is separately recorded as `workflow_sha`.
Product version alone is not source identity. The unchanged builder uses
`-ValidationScope UiPreview`: `validation_scope=windows-ui-preview`, `full_release=false`.
Formal release remains BLOCKED by Maotai `torso_neutral.png`; no substitute asset or gate bypass.

## Authority: preparation only

Nothing here authorizes operation of the user's Windows/Mac, installation, login/startup,
ComfyUI, models, GPU or real jobs. The existing electrical stop remains in force.
Only after qualified electrical clearance AND explicit user approval for the relevant action
may the following be performed. CI is a disposable GitHub runner, not the user workstation.
Native startup is not real two-host/GPU/video acceptance.

## Generic package README warning

Do NOT immediately double-click generic `INSTALL_PHASE2_WINDOWS.vbs`, VERIFY or ROLLBACK
launchers in the inner ZIP. Normal installation launches GUI, and GUI automatically starts
`Picotoo Pet AI.exe --p0-media-worker`, even before pairing. Window close is not worker stop.
No config AND no `.armed` marker means unattended operation, NOT HOLD.
This READ-FIRST document takes precedence over generic instructions for this preview.
Original installer/builder/production source is unchanged.

## Short safe deployment sequence (future authorized operator action)

1. Download the complete CI artifact, not just the EXE. Validate the inner ZIP SHA256 against
   `p0-developer-preview-evidence.json` and the ZIP `.sha256.txt`; extract its single directory.
   Check `release-manifest.json`: exact `source_head` above, `full_release=false`,
   `validation_scope=windows-ui-preview`, `native_ci_verified=true`. Match `github_run_id` to
   the successful preview run. Match EXE hash against manifest AND evidence. Dependencies and
   all payload sizes/hashes are in the manifest; .NET/native libraries may be embedded in the
   self-contained single-file EXE. Unsigned CI is not public signing; do not globally weaken
   SmartScreen or system policy.
2. Require old GUI/worker stopped through the already-authorized explicit Exit flow AND all
   accepted Comfy jobs drained/accounted for. Do not force-kill active GPU work or delete
   journals. HOLD cannot cancel an accepted prompt; old binaries may ignore HOLD. Unknown
   process/task/queue state means BLOCKED, not permission to run an installer that kills them.
3. Under the SAME Windows account that will run the app, prepare HOLD before installation
   activation and before any login/startup shortcut. Fixed path:
   `%LOCALAPPDATA%\PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json`, NOT DesktopApp,
   the package, Comfy input or Mac. Use the known-folder path; do not redirect it or use links.

```powershell
# Future operator action ONLY after electrical + installation approval; NOT run by Codex.
$ErrorActionPreference = 'Stop'
if (@(Get-CimInstance Win32_Process -Filter "Name='Picotoo Pet AI.exe'").Count) {
  throw 'GUI/worker still running; stop safely and account for accepted jobs first.'
}
$gate = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json'
$folder = Split-Path -Parent $gate
for ($p = [IO.DirectoryInfo]::new($folder); $null -ne $p; $p = $p.Parent) {
  if ($p.Exists -and ($p.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Reparse directory forbidden' }
}
[IO.Directory]::CreateDirectory($folder) | Out-Null
foreach ($p in @($gate, ($gate + '.armed'))) {
  if ((Test-Path -LiteralPath $p) -and ((Get-Item -LiteralPath $p -Force).Attributes -band ([IO.FileAttributes]::ReparsePoint -bor [IO.FileAttributes]::Directory))) { throw 'Unsafe gate/marker' }
}
# Marker guards missing config. Only completed replacement revokes any existing ALLOW.
$marker = [IO.File]::Open($gate + '.armed', [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write, [IO.FileShare]::Read)
try { if ($marker.Length -eq 0) { $marker.WriteByte(1) }; $marker.Flush($true) } finally { $marker.Dispose() }
$temp = Join-Path $folder ('.hold-' + [guid]::NewGuid().ToString('N') + '.tmp')
$stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $bytes = [Text.Encoding]::UTF8.GetBytes('{"schema_version":"1.0","mode":"hold"}'); $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
if ([IO.File]::Exists($gate)) { [IO.File]::Replace($temp, $gate, $null) } else { [IO.File]::Move($temp, $gate) }
$config = Get-Content -LiteralPath $gate -Raw | ConvertFrom-Json
if ($config.schema_version -ne '1.0' -or $config.mode -ne 'hold' -or -not [IO.File]::Exists($gate + '.armed')) { throw 'HOLD not verified' }
'HOLD_READY_BEFORE_FIRST_LAUNCH'
```

   An interrupted preparation is NOT a HOLD success: an existing ALLOW stays effective
   until the atomic replacement completes. Do not start/login/reboot before successful
   readback. If Startup may launch an old executable before that point, preparation is
   BLOCKED until the authorized operator has prevented that startup; this script does not
   disable shortcuts, revoke accepted prompts or make an old binary understand the gate.

4. From the extracted package use the EXISTING scripts without interactive activation:

```powershell
powershell.exe -NoProfile -File .\Install-Phase2Prebuilt.ps1 -ActivationSelfTest -SuppressReportOpen
if ($LASTEXITCODE) { throw 'INSTALL failed; do not launch' }
powershell.exe -NoProfile -File .\Verify-Phase2Prebuilt.ps1 -OfflinePackageOnly -SuppressReportOpen
if ($LASTEXITCODE) { throw 'VERIFY failed; do not launch' }
```

   This retains versioned installation and Desktop/Start Menu/Startup shortcuts. Self-test
   dispatches before normal session/worker startup. Check PASS reports under
   `%LOCALAPPDATA%\PicotooPetV2\DesktopApp\reports` and `current_version.json` version/EXE hash,
   then installed manifest source SHA. Do not use connected VERIFY yet: it can launch GUI and
   submit diagnostic/network tasks. Do not compile source or install an SDK on the user PC.
5. Only with separate explicit GUI-start approval, open the installed shortcut with HOLD and
   `.armed` intact. Verify compatible Core/Worker below first. No ALLOW procedure is provided:
   later separately authorized acceptance must review exact Job ID, canonical frozen Plan
   Digest and all three legal T2V tasks. Do not delete old unknown POSTs or `.armed` to unblock.

## Failure and rollback

If hash/self-test/install validation fails: STOP, do not launch. Existing installer restores
pre-activation pointers/shortcuts on activation failure. Before manual rollback require
idle/drained processes AND a verified HOLD-aware previous binary. Then use existing
`Rollback-Phase2Prebuilt.ps1 -ActivationSelfTest -SuppressReportOpen`, followed by
`Verify-Phase2Prebuilt.ps1 -OfflinePackageOnly -SuppressReportOpen`.
Keep HOLD/marker, pairing, databases, journals, results and old versions; never reset state.
If previous compatibility is unknown or it predates this gate, rollback activation and its
Startup shortcut are BLOCKED: that binary may ignore HOLD. Do not rely on window close or
the new version's marker to protect an old executable.

## Mac/Windows matching and unverified acceptance

Use Mac Core AND Mac Worker artifacts from the same `9b6faec72dfba7da0db31fcd2cbce5388480bb88`
candidate, or get G006's explicit commit-level compatibility statement for both. Product
version `2.3.27.1`, health=ok or main HEAD is insufficient. This source combines local Creative
three-shot T2V restrictions, durable claim/attempt recovery, the empty-identity fix and all
28 independent Windows gate cases. Core owns frozen Plans/authorization; Worker must actually
register the required local Creative capability. No Mac install/restart or model preload is
authorized by this packet.

Candidate native runs: Core 39535342656; Mac Worker 39535342805; Windows P0 39535342679;
WPF 39535342597; C011 39535342659. Formal Prebuilt 39535342613 failed the real missing
`torso_neutral.png` gate; it remains a separate BLOCKED release, not this preview's PASS.

User installed versions, electrical clearance, live Core/Worker, model residency, GPU prompt
IDs, three real WebMs, final MP4/receipt and visual acceptance remain UNVERIFIED. CI lifecycle
fixtures prove compatible-version mechanics, not the user's actual rollback target or
permission to start. No user installation or hardware operation is performed by this build.
