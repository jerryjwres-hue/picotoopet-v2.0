# P0 Developer Preview: prepare persistent HOLD before any GUI/Worker launch.
# Never starts the GUI, Mac service, ComfyUI, model or GPU.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw 'P0_HOLD_LOCALAPPDATA_UNAVAILABLE'
}
# Fail closed if any GUI / headless Worker is already running; do not interrupt in-flight tasks.
$running = @(Get-CimInstance Win32_Process -Filter "Name = 'Picotoo Pet AI.exe'")
if ($running.Count -gt 0) {
    throw 'P0_HOLD_APPLICATION_ALREADY_RUNNING: close GUI and Worker safely before preparing HOLD'
}

$directory = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1'
$path = Join-Path $directory 'three-shot-acceptance.json'
$markerPath = "$path.armed"

# Refuse redirected/symlinked gate directories and files.
for ($parent = [System.IO.DirectoryInfo]::new($directory); $null -ne $parent; $parent = $parent.Parent) {
    if ($parent.Exists -and (($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'P0_HOLD_REPARSE_DIRECTORY'
    }
}
New-Item -ItemType Directory -Path $directory -Force | Out-Null
foreach ($item in @($path, $markerPath)) {
    if (Test-Path -LiteralPath $item) {
        if (((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'P0_HOLD_REPARSE_FILE'
        }
    }
}

# Arm FIRST, before publishing any acceptance JSON. If anything after this fails,
# the persistent marker prevents a restarted Worker from falling back to unattended mode.
$marker = $null
try {
    $marker = [IO.FileStream]::new($markerPath,
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::Write,
        [IO.FileShare]::Read, 8, [IO.FileOptions]::WriteThrough)
    if ($marker.Length -eq 0) {
        $marker.WriteByte(1)
    }
    $marker.Flush($true)
}
finally {
    if ($null -ne $marker) { $marker.Dispose() }
}
if (-not [IO.File]::Exists($markerPath) -or
    [IO.File]::ReadAllBytes($markerPath).Length -lt 1) {
    throw 'P0_HOLD_ARMED_MARKER_VERIFY_FAILED'
}

# Atomically publish complete UTF-8-no-BOM HOLD; never expose partially written JSON.
$json = '{"schema_version":"1.0","mode":"hold"}' + [Environment]::NewLine
$temp = Join-Path $directory ("three-shot-acceptance." + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllText($temp, $json, [Text.UTF8Encoding]::new($false))
    if ([IO.File]::Exists($path)) {
        [IO.File]::Replace($temp, $path, $null)
    }
    else {
        [IO.File]::Move($temp, $path)
    }
}
finally {
    if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
}

$actual = [IO.File]::ReadAllText($path, [Text.UTF8Encoding]::new($false)) | ConvertFrom-Json
if ($actual.schema_version -ne '1.0' -or $actual.mode -ne 'hold' -or
    -not [IO.File]::Exists($markerPath) -or
    [IO.File]::ReadAllBytes($markerPath).Length -lt 1) {
    throw 'P0_HOLD_VERIFY_FAILED'
}
if (@(Get-CimInstance Win32_Process -Filter "Name = 'Picotoo Pet AI.exe'").Count -gt 0) {
    throw 'P0_HOLD_APPLICATION_STARTED_DURING_PREPARATION'
}
Write-Host "P0_HOLD_PREPARED=PASS; ARMED=PASS; PATH=$path"
Write-Host 'This does not open the GUI or authorize a GPU submission.'
