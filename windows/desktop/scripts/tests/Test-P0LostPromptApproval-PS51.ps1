# Native Windows PowerShell 5.1 test of operator script; all inputs fake, no GPU, no network.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ApprovalScript)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'P0_PS51_REQUIRED' }
$scriptPath = (Resolve-Path -LiteralPath $ApprovalScript).Path
$originalAppData = $env:LOCALAPPDATA
$temp = Join-Path $env:TEMP ('p0-approval-ps51-' + [guid]::NewGuid().ToString('N'))
$job = '64695948-fb1a-4793-815f-3f6ad4d4d536'
$task3 = '6bf92cbf-22a0-5cb6-9884-67dca7d3ab12'
$prompt = 'bdc2dd33-f0ef-4bc1-83c1-b579de70751f'
$digest = '60432b2be69b945cb29ea88eeabac26d82574f470a36981dda5725a92ea6aa04'
$root = Join-Path $temp 'PicotooPetV2\MediaWorker\v1'
$approval = Join-Path $root 'lost-prompt-attempt2-approval.json'
$gate = Join-Path $root 'three-shot-acceptance.json'
try {
    $env:LOCALAPPDATA = $temp
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    $enc = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($gate, '{"schema_version":"1.0","mode":"hold"}', $enc)
    [IO.File]::WriteAllBytes("$gate.armed", [byte[]]@(1))

    $completed = @(
        @{ JobId=$job; TaskId='79165e15-1a18-5814-886f-6f1ceae0f7f0'; PlanDigest=$digest; Phase='Settled'; PromptId='e349225c-d52e-4dea-a10d-e0976694e5fe' },
        @{ JobId=$job; TaskId='b5008430-1b1e-5116-810a-8ad5bd72349d'; PlanDigest=$digest; Phase='Settled'; PromptId='578a28d0-09ec-4a54-a279-c6cc3aa4f77f' },
        @{ JobId=$job; TaskId=$task3; PlanDigest=$digest; Phase='Submitted'; PromptId=$prompt }
    )
    for ($i = 0; $i -lt $completed.Count; $i++) {
        $file = Join-Path $root ("task-$i.submission.json")
        [IO.File]::WriteAllText($file, ($completed[$i] | ConvertTo-Json -Compress), $enc)
    }
    $out = Join-Path $temp "Comfy-Desktop\ComfyUI-Shared\output\PicotooPet\production\$job"
    New-Item -ItemType Directory -Path $out -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $out '001-shot-01_00001_.webm'), 'fake-one', $enc)
    [IO.File]::WriteAllText((Join-Path $out '002-shot-02_00001_.webm'), 'fake-two', $enc)

    # Stub only the two external, read-only commands in this isolated fixture.
    function Get-CimInstance { param([string]$ClassName, [string]$Filter) }
    function Invoke-RestMethod {
        param([string]$Uri, [int]$TimeoutSec)
        if ($Uri -eq 'http://127.0.0.1:8188/queue') {
            return [pscustomobject]@{ queue_running = @(); queue_pending = @() }
        }
        if ($Uri -match '^http://127\.0\.0\.1:8188/history/') {
            return [pscustomobject]@{}
        }
        throw "UNEXPECTED_NETWORK_ENDPOINT $Uri"
    }

    # Identity mismatch may NEVER publish approval or switch HOLD->ALLOW.
    $rejected = $false
    try {
        & $scriptPath -ProductionJobId $job -ProductionTaskId 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' -PreviousPromptId $prompt -PlanDigest $digest -AuthorizeOneNewGpuPost
    } catch {
        if ($_.Exception.Message -match 'P0_OLD_PROMPT_NOT_EXACTLY_SUBMITTED') { $rejected = $true } else { throw }
    }
    if (-not $rejected -or [IO.File]::Exists($approval)) { throw 'P0_PS51_MISMATCH_MUST_HOLD' }
    $h = Get-Content -LiteralPath $gate -Raw | ConvertFrom-Json
    if ($h.mode -ne 'hold') { throw 'P0_PS51_EARLY_WRITE_INVALID' }

    # Exact-ID authorized case, fake Comfy/outputs only. Never executes real Worker.
    & $scriptPath -ProductionJobId $job -ProductionTaskId $task3 -PreviousPromptId $prompt -PlanDigest $digest -AuthorizeOneNewGpuPost
    $check = Get-Content -LiteralPath $gate -Raw | ConvertFrom-Json
    $a = Get-Content -LiteralPath $approval -Raw | ConvertFrom-Json
    if ($check.mode -ne 'allow' -or $check.production_job_id -ne $job -or
        $a.previous_prompt_id -ne $prompt -or $a.production_task_id -ne $task3) {
        throw 'P0_PS51_APPROVAL_WRITE_INVALID'
    }
    Write-Host 'P0_PS51_LOST_PROMPT_APPROVAL=PASS; FAKE_GPU_POST=0'
}
finally {
    $env:LOCALAPPDATA = $originalAppData
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
}
