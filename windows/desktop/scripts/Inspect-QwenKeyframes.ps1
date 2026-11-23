# PicotooPet Windows Qwen first-frame offline inspection.
# Reads only direct Comfy output PNGs. Writes only a new JSON report in TEMP.
# Never launches Comfy, calls the API, modifies an image or enables the GPU.
[CmdletBinding()]
param(
    [string]$OutputRoot,
    [string]$InputRoot,
    [int]$ExpectedCount = 6
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 01. Auto-locate the *observed* Comfy Desktop shared output, never scan
#     other drives, old missing installations or the user's private folders.
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Shared\output'
}
if (-not (Test-Path -LiteralPath $OutputRoot -PathType Container)) {
    throw 'QWEN_INSPECT_COMFY_OUTPUT_NOT_FOUND'
}
if ($ExpectedCount -lt 1 -or $ExpectedCount -gt 64) {
    throw 'QWEN_INSPECT_EXPECTED_COUNT_INVALID'
}

# 02. Inspect the sibling Comfy input directory when it exists. This never
#     searches a drive or decides whether a file is an S2/S3 composition.
#     An explicit -InputRoot must exist; the optional auto-path may be absent.
if ([string]::IsNullOrWhiteSpace($InputRoot)) {
    $sibling = Join-Path (Split-Path -Parent $OutputRoot) 'input'
    if (Test-Path -LiteralPath $sibling -PathType Container) {
        $InputRoot = $sibling
    }
}
elseif (-not (Test-Path -LiteralPath $InputRoot -PathType Container)) {
    throw 'QWEN_INSPECT_COMFY_INPUT_NOT_FOUND'
}

# 03. No Python install is attempted. Missing Python is a safe STOP.
$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python -or $python.CommandType -notin @('Application', 'ExternalScript')) {
    throw 'QWEN_INSPECT_PYTHON_NOT_AVAILABLE'
}
$pythonVersion = & $python.Source -c 'import sys; print(int(sys.version_info >= (3, 12)))'
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '1') {
    throw 'QWEN_INSPECT_PYTHON_312_REQUIRED'
}
$bundle = Split-Path -Parent $PSCommandPath
$audit = Join-Path $bundle 'scripts\audit_local_qwen_pngs.py'
if (-not (Test-Path -LiteralPath $audit -PathType Leaf)) {
    throw 'QWEN_INSPECT_BUNDLED_TOOL_MISSING'
}

# 03. Preserve the exact Comfy input/output files and app settings.
#     The only new output is a private, never-overwritten JSON in TEMP.
$report = Join-Path $env:TEMP ("picotoo-qwen-inspection-{0}.json" -f [Guid]::NewGuid().ToString('N'))
$priorPath = $env:PYTHONPATH
$priorBytecode = $env:PYTHONDONTWRITEBYTECODE
Push-Location $bundle
try {
    $env:PYTHONPATH = $bundle
    $env:PYTHONDONTWRITEBYTECODE = '1'
    # 04. Argument-array invocation prevents filename/path fragments from
    #     becoming PowerShell commands. No additional files are created.
    $auditArgs = @('-B', $audit, '--output-root', $OutputRoot,
                   '--expected-count', [string]$ExpectedCount,
                   '--report-file', $report)
    if (-not [string]::IsNullOrWhiteSpace($InputRoot)) {
        $auditArgs += @('--input-root', $InputRoot)
    }
    & $python.Source @auditArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "QWEN_INSPECTION=UNVERIFIED; REPORT=$report; GPU_POST=0"
        throw 'QWEN_INSPECT_INVENTORY_NOT_VERIFIED'
    }
}
finally {
    $env:PYTHONPATH = $priorPath
    $env:PYTHONDONTWRITEBYTECODE = $priorBytecode
    Pop-Location
}
Write-Host "QWEN_INSPECTION=OBSERVED_NEEDS_REVIEW; REPORT=$report; GPU_POST=0"
if ([string]::IsNullOrWhiteSpace($InputRoot)) {
    Write-Host 'QWEN_REFERENCED_INPUTS=NOT_CHECKED; S2_S3_ASSIGNMENT=UNVERIFIED'
}
Write-Host 'COMFY_POST=0; MODEL_INFERENCE=NOT_RUN; PRODUCTION_AUTHORIZED=FALSE'
