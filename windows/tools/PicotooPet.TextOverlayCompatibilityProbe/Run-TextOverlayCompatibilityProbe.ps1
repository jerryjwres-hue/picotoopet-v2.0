#requires -Version 5.1
<#
.SYNOPSIS
  S004 deterministic Windows build + run command for the isolated text-overlay compatibility probe.
.DESCRIPTION
  Builds only the probe project (never the Desktop solution), enforces a static no-network/no-shell/
  no-arbitrary-font source scan, then runs: self-test, simulated missing-font path, and the real probe
  against the installed ffmpeg.exe/ffprobe.exe on PATH. Exit 0 only when every step behaves as specified
  and at least one overlay path passes. Install the SDK pinned by windows/desktop/global.json first.
#>
[CmdletBinding()]
param(
  [string]$Configuration = 'Release',
  [ValidateRange(5, 120)][int]$TimeoutSeconds = 60,
  [string]$ReportPath = (Join-Path ([IO.Path]::GetTempPath()) 'picotoopet-s004-text-overlay-report.json')
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'S004 probe requires native Windows.' }

$projectDir = $PSScriptRoot
$project = Join-Path $projectDir 'PicotooPet.TextOverlayCompatibilityProbe.csproj'

# ── Static authority scan ──
$forbidden = 'HttpClient|WebClient|System\.Net\.|Socket|UseShellExecute\s*=\s*true|cmd\.exe|powershell|pwsh|magick|chromium|WebView|api_?key|password|secret|GetEnvironmentVariable'
$hits = Get-ChildItem -Path $projectDir -Filter *.cs -Recurse |
  Where-Object { $_.FullName -notmatch '[\\/](obj|bin)[\\/]' } |
  Select-String -Pattern $forbidden
if ($hits) { $hits | ForEach-Object { Write-Error "Forbidden authority: $($_.Path):$($_.LineNumber)" }; exit 10 }

dotnet --info | Out-Host
dotnet build $project --configuration $Configuration | Out-Host
if ($LASTEXITCODE -ne 0) { exit 11 }
$exe = Get-ChildItem -Path (Join-Path $projectDir "bin\$Configuration") -Filter 'PicotooPet.TextOverlayCompatibilityProbe.exe' -Recurse |
  Select-Object -First 1
if (-not $exe) { Write-Error 'Probe executable not found after build.'; exit 12 }

# 1) Pure-logic self-test (cmap reader, frame analyzer, ASS/filter builders, unsafe-name denial)
& $exe.FullName --self-test | Out-Host
if ($LASTEXITCODE -ne 0) { exit 13 }

# 2) Missing-font path must fail in a bounded way for every path
$noFont = (& $exe.FullName --simulate-no-font --timeout-seconds $TimeoutSeconds | Out-String) | ConvertFrom-Json
if (@($noFont.paths | Where-Object { $_.status -notin @('FONT_UNAVAILABLE', 'FILTER_MISSING', 'ENCODER_MISSING', 'FFMPEG_UNAVAILABLE') }).Count -ne 0) {
  Write-Error 'Missing-font path did not fail with a bounded code.'; exit 14
}

# 3) Real probe; report is evidence for docs/architecture/video/S004_WINDOWS_TEXT_OVERLAY_RESULT.md
$json = (& $exe.FullName --timeout-seconds $TimeoutSeconds | Out-String)
$probeExit = $LASTEXITCODE
Set-Content -Path $ReportPath -Value $json -Encoding UTF8
$json | Out-Host
Write-Host "Report written to $ReportPath (probe exit $probeExit)"
exit $probeExit
