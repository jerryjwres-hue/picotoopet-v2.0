# One-time operator approval for P0 shot3 after a confirmed Windows reboot.
# DOES NOT launch PicotooPet, Comfy, models, or itself POST GPU tasks.
# Requires a *new explicit operator decision* to permit exactly one bounded attempt2.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProductionJobId,
    [Parameter(Mandatory=$true)][string]$ProductionTaskId,
    [Parameter(Mandatory=$true)][string]$PreviousPromptId,
    [Parameter(Mandatory=$true)][string]$PlanDigest,
    [Parameter(Mandatory=$true)][switch]$AuthorizeOneNewGpuPost
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $AuthorizeOneNewGpuPost) { throw 'P0_OPERATOR_GPU_AUTHORIZATION_REQUIRED' }
$parsedJob = [guid]::Empty
if (-not [guid]::TryParse($ProductionJobId, [ref]$parsedJob)) {
    throw 'P0_JOB_UUID_INVALID'
}
if ($PlanDigest -cnotmatch '^[0-9a-f]{64}$' -or
    $ProductionTaskId -notmatch '^[0-9a-fA-F-]{36}$' -or
    $PreviousPromptId -notmatch '^[0-9a-fA-F-]{36}$') {
    throw 'P0_ATTEMPT2_IDENTITY_INVALID'
}
$procs = @(Get-CimInstance Win32_Process -Filter "Name='Picotoo Pet AI.exe'")
if ($procs.Count -ne 0) { throw 'P0_STOP_ALL_GUI_AND_WORKER_FIRST' }

$root = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1'
$gate = Join-Path $root 'three-shot-acceptance.json'
$armed = "$gate.armed"
$approval = Join-Path $root 'lost-prompt-attempt2-approval.json'
foreach ($parent in @($root)) {
    for ($p = [System.IO.DirectoryInfo]::new($parent); $null -ne $p; $p = $p.Parent) {
        if ($p.Exists -and (($p.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            throw 'P0_REPARSE_ROOT_REJECTED'
        }
    }
}
foreach ($item in @($gate, $armed, $approval)) {
    if ([IO.File]::Exists($item) -and
        (((Get-Item -LiteralPath $item).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'P0_REPARSE_FILE_REJECTED'
    }
}
if (-not ([IO.File]::Exists($armed) -and [IO.File]::Exists($gate))) {
    throw 'P0_PERSISTENT_HOLD_NOT_ARMED'
}
$g = Get-Content -LiteralPath $gate -Raw | ConvertFrom-Json
if ($g.schema_version -ne '1.0' -or $g.mode -ne 'hold' -or
    @($g.PSObject.Properties | ForEach-Object { $_.Name }).Count -ne 2) { throw 'P0_NOT_IN_STRICT_HOLD' }
if ([IO.File]::Exists($approval)) {
    throw 'P0_APPROVAL_ALREADY_EXISTS_STOP_AND_REVIEW'
}

$records = @(Get-ChildItem -LiteralPath $root -Filter '*.submission.json' -File |
    ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json })
if (@($records | Where-Object { $_.JobId -ne $ProductionJobId -and $_.Phase -ne 'Settled' }).Count -ne 0) {
    throw 'P0_OTHER_PENDING_JOB_EXISTS'
}
$mine = @($records | Where-Object { $_.JobId -eq $ProductionJobId })
if ($mine.Count -ne 3 -or @($mine | Where-Object { $_.Phase -eq 'Settled' }).Count -ne 2) {
    throw 'P0_COMPLETED_SHOT_IDENTITY_MISMATCH'
}
$third = @($mine | Where-Object { $_.TaskId -eq $ProductionTaskId })
if ($third.Count -ne 1 -or $third[0].Phase -ne 'Submitted' -or
    $third[0].PromptId -ne $PreviousPromptId -or
    $third[0].PlanDigest -ne $PlanDigest) {
    throw 'P0_OLD_PROMPT_NOT_EXACTLY_SUBMITTED'
}

$q = Invoke-RestMethod 'http://127.0.0.1:8188/queue' -TimeoutSec 10
if (@($q.queue_running).Count -ne 0 -or @($q.queue_pending).Count -ne 0) {
    throw 'P0_COMFY_QUEUE_NOT_IDLE'
}
$history = Invoke-RestMethod ('http://127.0.0.1:8188/history/' + [Uri]::EscapeDataString($PreviousPromptId)) -TimeoutSec 10
if ($null -ne $history.PSObject.Properties[$PreviousPromptId]) {
    throw 'P0_OLD_PROMPT_PRESENT_IN_COMFY_HISTORY'
}
$out = Join-Path $env:LOCALAPPDATA "Comfy-Desktop\ComfyUI-Shared\output\PicotooPet\production\$ProductionJobId"
if (@(Get-ChildItem -LiteralPath $out -Filter '001-shot-01*.webm' -File -ErrorAction SilentlyContinue).Count -ne 1 -or
    @(Get-ChildItem -LiteralPath $out -Filter '002-shot-02*.webm' -File -ErrorAction SilentlyContinue).Count -ne 1 -or
    @(Get-ChildItem -LiteralPath $out -Filter '003-shot-03*.webm' -File -ErrorAction SilentlyContinue).Count -ne 0) {
    throw 'P0_OUTPUTS_NOT_EXACT_TWO'
}

# New UTC operator decision after reboot, verified again independently inside same-EXE Worker.
$data = [ordered]@{
    schema_version = 'p0.lost-prompt-attempt2.v1'
    production_job_id = $ProductionJobId
    production_task_id = $ProductionTaskId
    previous_prompt_id = $PreviousPromptId
    plan_digest = $PlanDigest
    authorized_at_utc = [DateTimeOffset]::UtcNow.ToString('O')
} | ConvertTo-Json -Compress
$allow = [ordered]@{
    schema_version = '1.0'
    mode = 'allow'
    production_job_id = $ProductionJobId
    plan_digest = $PlanDigest
} | ConvertTo-Json -Compress

$temporary = Join-Path $root ([guid]::NewGuid().ToString('N') + '.approval.tmp')
$gateTemp = Join-Path $root ([guid]::NewGuid().ToString('N') + '.gate.tmp')
$gateBackup = Join-Path $root ([guid]::NewGuid().ToString('N') + '.gate.bak')
try {
    $enc = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temporary, $data, $enc)
    # Moving the approval atomically is safe because GUI and Worker remain stopped.
    [IO.File]::Move($temporary, $approval)
    [IO.File]::WriteAllText($gateTemp, $allow, $enc)
    [IO.File]::Replace($gateTemp, $gate, $gateBackup)
    $check = Get-Content $gate -Raw | ConvertFrom-Json
    if ($check.mode -ne 'allow' -or $check.production_job_id -ne $ProductionJobId -or
        $check.plan_digest -ne $PlanDigest -or
        @(Get-CimInstance Win32_Process -Filter "Name='Picotoo Pet AI.exe'").Count -ne 0) {
        throw 'P0_FINAL_RECHECK_FAILED'
    }
}
finally {
    foreach ($temp in @($temporary,$gateTemp)) {
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
    }
}
Write-Host 'P0_EXACT_ATTEMPT2_ALLOW=PASS'
Write-Host 'This only grants the same-EXE Worker an exact time-limited attempt2 opportunity.'
Write-Host 'DO NOT manually POST /prompt; start verified Preview GUI only after this PASS.'
