#requires -Version 5.1
<#
.SYNOPSIS
  S003 deterministic Windows build + run command for the isolated TTS compatibility probe.
.DESCRIPTION
  Builds only the probe project (never the Desktop solution), enforces a static no-network/
  no-process/no-credential source scan, then runs: self-test, simulated no-voice, and the real
  engine probe. Exit 0 only when every step behaves as specified and at least one engine passes.
  Install the SDK pinned by windows/desktop/global.json first (CI: actions/setup-dotnet global-json-file).
#>
[CmdletBinding()]
param(
  [string]$Configuration = 'Release',
  [ValidateRange(1, 60)][int]$TimeoutSeconds = 20,
  [string]$ReportPath = (Join-Path ([IO.Path]::GetTempPath()) 'picotoopet-s003-tts-report.json')
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'S003 probe requires native Windows.' }

$projectDir = $PSScriptRoot
$project = Join-Path $projectDir 'PicotooPet.TtsCompatibilityProbe.csproj'

# ── Static authority scan: probe must have no network/process/credential/path-input surface ──
$forbidden = 'HttpClient|WebClient|System\.Net\.|Socket|Process\.Start|ProcessStartInfo|Environment\.GetEnvironmentVariable|api_?key|password|secret|\.onnx|\.gguf'
$hits = Get-ChildItem -Path $projectDir -Filter *.cs -Recurse |
  Where-Object { $_.FullName -notmatch '[\\/](obj|bin)[\\/]' } |
  Select-String -Pattern $forbidden
if ($hits) { $hits | ForEach-Object { Write-Error "Forbidden authority: $($_.Path):$($_.LineNumber)" }; exit 10 }

dotnet --info | Out-Host
dotnet build $project --configuration $Configuration | Out-Host
if ($LASTEXITCODE -ne 0) { exit 11 }

$exe = Get-ChildItem -Path (Join-Path $projectDir "bin\$Configuration") -Filter 'PicotooPet.TtsCompatibilityProbe.exe' -Recurse |
  Select-Object -First 1
if (-not $exe) { Write-Error 'Probe executable not found after build.'; exit 12 }

# 1) Validator/selection self-test (no voices required)
& $exe.FullName --self-test | Out-Host
if ($LASTEXITCODE -ne 0) { exit 13 }

# 2) Missing-voice path must yield bounded NO_COMPATIBLE_VOICE for every engine
$noVoice = (& $exe.FullName --simulate-no-voice --timeout-seconds $TimeoutSeconds | Out-String) | ConvertFrom-Json
if (@($noVoice.engines | Where-Object { $_.status -ne 'NO_COMPATIBLE_VOICE' }).Count -ne 0) {
  Write-Error 'Missing-voice path did not return NO_COMPATIBLE_VOICE for every engine.'; exit 14
}

# 3) Real probe; report is evidence for docs/architecture/video/S003_WINDOWS_LOCAL_TTS_RESULT.md
$json = (& $exe.FullName --timeout-seconds $TimeoutSeconds | Out-String)
$probeExit = $LASTEXITCODE
Set-Content -Path $ReportPath -Value $json -Encoding UTF8
$json | Out-Host
Write-Host "Report written to $ReportPath (probe exit $probeExit)"
exit $probeExit
