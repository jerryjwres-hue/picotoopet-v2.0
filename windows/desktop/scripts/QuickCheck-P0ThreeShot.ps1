# PicotooPet P0: one explicit Windows HOLD-first offline local check.
# This script reuses the two existing reviewed entrypoints, not a new worker.
# Only allowed writes: persistent local GPU HOLD and one private TEMP JSON.
# No app launch, SSH, HTTP, Comfy POST, model inference or image mutation.
[CmdletBinding()]
param(
    [string]$OutputRoot,
    [string]$InputRoot,
    [int]$ExpectedCount = 6
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$bundle = Split-Path -Parent $PSCommandPath
$hold = Join-Path $bundle 'Prepare-P0ThreeShotHold.ps1'
$inspect = Join-Path $bundle 'Inspect-QwenKeyframes.ps1'

try {
    # 01. Reject an incomplete bundle before touching local configuration.
    #     The archive's complete SHA manifest must be verified separately.
    if (-not (Test-Path -LiteralPath $hold -PathType Leaf) -or
        -not (Test-Path -LiteralPath $inspect -PathType Leaf)) {
        throw 'P0_LOCAL_QUICKCHECK_BUNDLE_INCOMPLETE'
    }

    # 02. Arm and verify permanent HOLD first, using the existing idempotent
    #     native implementation. An already-running worker is a hard STOP.
    & $hold

    # 03. Scope file inspection to the observed Comfy Desktop folders only;
    #     never enumerate drives, home directories or unknown installations.
    if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
        if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            throw 'P0_LOCAL_QUICKCHECK_LOCALAPPDATA_UNAVAILABLE'
        }
        $OutputRoot = Join-Path $env:LOCALAPPDATA 'Comfy-Desktop\ComfyUI-Shared\output'
    }
    if ([string]::IsNullOrWhiteSpace($InputRoot)) {
        $InputRoot = Join-Path (Split-Path -Parent $OutputRoot) 'input'
    }
    if (-not (Test-Path -LiteralPath $OutputRoot -PathType Container) -or
        -not (Test-Path -LiteralPath $InputRoot -PathType Container)) {
        throw 'P0_LOCAL_QUICKCHECK_COMFY_FOLDERS_UNAVAILABLE'
    }

    # 04. Reuse the exact existing read-only six-PNG/output-input verifier.
    #     It creates only one non-overwritten JSON in the user's TEMP folder.
    $inspection = (& $inspect -OutputRoot $OutputRoot -InputRoot $InputRoot -ExpectedCount $ExpectedCount | Out-String)
    Write-Output $inspection.TrimEnd()

    # 05. The historical PNG audit may pass while an input asset is missing.
    #     Fail the combined check unless every exact referenced input byte
    #     was verified, using the newly created private JSON evidence.
    $reportLines = @($inspection -split "\r?\n" | Where-Object {
        $_ -like 'QWEN_INSPECTION=OBSERVED_NEEDS_REVIEW; REPORT=*; GPU_POST=0'
    })
    if ($reportLines.Count -ne 1) {
        throw 'P0_LOCAL_QUICKCHECK_REPORT_UNVERIFIED'
    }
    $prefix = 'QWEN_INSPECTION=OBSERVED_NEEDS_REVIEW; REPORT='
    $end = $reportLines[0].LastIndexOf('; GPU_POST=0', [StringComparison]::Ordinal)
    if ($end -le $prefix.Length) {
        throw 'P0_LOCAL_QUICKCHECK_REPORT_PATH_INVALID'
    }
    $reportPath = $reportLines[0].Substring($prefix.Length, $end - $prefix.Length)
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $inventory = $report.referenced_input_inventory
    if ($report.status -ne 'OBSERVED_NEEDS_REVIEW' -or
        $null -eq $inventory -or
        $inventory.status -ne 'ALL_REFERENCED_INPUT_BYTES_OBSERVED' -or
        $inventory.referenced_file_count -lt 1 -or
        $inventory.referenced_file_count -ne $inventory.observed_file_count -or
        $inventory.shot_2_3_assignment -ne 'UNVERIFIED' -or
        $inventory.gpu_post -ne 0) {
        throw 'P0_LOCAL_QUICKCHECK_REFERENCED_INPUTS_UNVERIFIED'
    }

    # 06. The result is an operator inventory, never Owner approval or proof
    #     of distinct S2/S3 images. The persistent GPU HOLD stays armed.
    Write-Host 'P0_LOCAL_QUICKCHECK=PASS; GPU_HOLD=HOLD; COMFY_POST=0; MODEL_INFERENCE=NOT_RUN'
    Write-Host 'S2_S3_COMPOSITION=UNVERIFIED; OWNER_APPROVAL=NOT_GRANTED; FORMAL_RELEASE=BLOCKED'
}
catch {
    # 07. Never suppress a failed HOLD/inspection or promise readiness.
    #     This branch does not attempt to fix, restart or run any service.
    Write-Host 'P0_LOCAL_QUICKCHECK=BLOCKED; GPU_POST=0; PRODUCTION_AUTHORIZED=FALSE'
    throw
}
