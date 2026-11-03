#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProductionJobId = '64695948-fb1a-4793-815f-3f6ad4d4d536',
    [string]$CoreUrl = 'http://192.168.68.70:8766',
    [string]$ComfyOutputRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Execution policy  : observe one immutable completed Job; never create GPU work.
# ── File policy       : source WebMs are read-only; evidence goes outside Comfy.
# ── Network policy    : authenticated GETs only; no frames leave this Windows PC.
$gatePath = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\MediaWorker\v1\three-shot-acceptance.json'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$credential = $null
$headers = $null

try {
    if (-not (Test-Path -LiteralPath $gatePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath ($gatePath + '.armed') -PathType Leaf)) {
        throw 'STOP_GPU_HOLD_NOT_CONFIRMED'
    }
    $gate = Get-Content -LiteralPath $gatePath -Raw | ConvertFrom-Json
    if ($gate.mode -ne 'hold') {
        throw 'STOP_GPU_HOLD_NOT_CONFIRMED'
    }
    if ($CoreUrl -ne 'http://192.168.68.70:8766') {
        throw 'STOP_CORE_ADDRESS_NOT_PINNED'
    }
    if (-not [guid]::TryParse($ProductionJobId, [ref]([guid]::Empty))) {
        throw 'STOP_INVALID_JOB_ID'
    }

    # ── Credential       : native read-only Windows vault; do not echo or persist token.
    if (-not ([System.Management.Automation.PSTypeName]'PicotooQualityCredential').Type) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class PicotooQualityCredential
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Credential
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string Comment;
        public long LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredReadW",
        CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(
        string target, uint type, uint flags, out IntPtr pointer);

    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr pointer);

    public static string Read()
    {
        IntPtr pointer;
        if (!CredRead("PicotooPetV2/MacCoreApiToken", 1, 0, out pointer))
            throw new InvalidOperationException("STOP_VAULT_CREDENTIAL_UNAVAILABLE");
        try
        {
            Credential c = (Credential)Marshal.PtrToStructure(
                pointer, typeof(Credential));
            if (c.CredentialBlob == IntPtr.Zero ||
                c.CredentialBlobSize == 0 || c.CredentialBlobSize > 4096)
                throw new InvalidOperationException("STOP_VAULT_CREDENTIAL_INVALID");
            byte[] bytes = new byte[(int)c.CredentialBlobSize];
            Marshal.Copy(c.CredentialBlob, bytes, 0, bytes.Length);
            try { return Encoding.Unicode.GetString(bytes); }
            finally { Array.Clear(bytes, 0, bytes.Length); }
        }
        finally { CredFree(pointer); }
    }
}
'@
    }

    $credential = [PicotooQualityCredential]::Read()
    $headers = @{ Authorization = "Bearer $credential" }
    $endpoint = "$CoreUrl/api/v1/production/jobs/$ProductionJobId"

    # ── Provenance       : GET exact Core Job, frozen Plan and PASS Package only.
    $job = Invoke-RestMethod -Uri $endpoint -Headers $headers -Method Get -TimeoutSec 20
    $plan = Invoke-RestMethod -Uri "$endpoint/plan" -Headers $headers -Method Get -TimeoutSec 20
    $package = Invoke-RestMethod -Uri "$endpoint/package" -Headers $headers -Method Get -TimeoutSec 20
    if ($job.status -ne 'production_ready' -or
        $package.quality_outcome -ne 'PASS' -or
        $job.production_job_id -ne $ProductionJobId -or
        $plan.production_job_id -ne $ProductionJobId -or
        $package.production_job_id -ne $ProductionJobId -or
        $package.plan_digest -ne $job.plan_digest -or
        $plan.creative_package_id -ne $job.creative_package_id -or
        $package.creative_package_id -ne $job.creative_package_id -or
        $plan.creative_package_digest -ne $job.creative_package_digest) {
        throw 'STOP_CORE_IDENTITY_OR_PACKAGE_NOT_READY'
    }

    $tasks = @($plan.tasks | Where-Object { $null -ne $_ } | Sort-Object order)
    $outputs = @($package.manifest.outputs | Where-Object { $null -ne $_ })
    if ($tasks.Count -ne 3 -or $outputs.Count -ne 3) {
        throw 'STOP_NOT_EXACT_THREE_SHOTS'
    }

    # ── Output root      : same configured/known candidates as production;
    # ──                    never scan disks for replacement or altered media.
    if ([string]::IsNullOrWhiteSpace($ComfyOutputRoot)) {
        $candidates = New-Object 'System.Collections.Generic.List[string]'
        $configPath = Join-Path $env:APPDATA 'ComfyUI\config.json'
        if (Test-Path -LiteralPath $configPath -PathType Leaf) {
            try {
                $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
                if (-not [string]::IsNullOrWhiteSpace([string]$config.basePath)) {
                    $candidates.Add([Environment]::ExpandEnvironmentVariables([string]$config.basePath))
                }
            }
            catch {
                throw 'STOP_COMFY_CONFIG_INVALID'
            }
        }
        foreach ($candidate in @(
            "$env:APPDATA\ComfyUI", "$env:LOCALAPPDATA\ComfyUI",
            "$env:USERPROFILE\ComfyUI", 'D:\ComfyUI',
            'D:\PicotooPet\ComfyUI', 'E:\ComfyUI'
        )) {
            $candidates.Add($candidate)
        }
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { continue }
            if ((Test-Path -LiteralPath (Join-Path $candidate 'models')) -or
                (Test-Path -LiteralPath (Join-Path $candidate 'custom_nodes')) -or
                (Test-Path -LiteralPath (Join-Path $candidate 'main.py')) -or
                (Test-Path -LiteralPath (Join-Path $candidate 'output'))) {
                $ComfyOutputRoot = Join-Path $candidate 'output'
                break
            }
        }
    }
    if (-not (Test-Path -LiteralPath $ComfyOutputRoot -PathType Container)) {
        throw 'STOP_COMFY_OUTPUT_ROOT_NOT_FOUND'
    }
    $ComfyOutputRoot = (Resolve-Path -LiteralPath $ComfyOutputRoot).Path

    # ── Media identity   : join exact task and shot IDs and verify bytes + hash.
    $shots = New-Object 'System.Collections.Generic.List[object]'
    foreach ($task in $tasks) {
        if ([int]$task.order -ne $shots.Count + 1 -or
            [string]::IsNullOrWhiteSpace([string]$task.production_task_id) -or
            [string]::IsNullOrWhiteSpace([string]$task.shot_id)) {
            throw 'STOP_TASK_ORDER_OR_IDENTITY'
        }
        $matches = @($outputs | Where-Object {
            $_.production_task_id -eq $task.production_task_id -and
            $_.shot_id -eq $task.shot_id
        })
        if ($matches.Count -ne 1) { throw 'STOP_OUTPUT_TASK_BINDING_MISMATCH' }
        $source = $matches[0]
        $relpath = [string]$source.output_relpath
        if ([IO.Path]::IsPathRooted($relpath) -or $relpath.Contains(':') -or
            $relpath -match '(^|[\\/])(\.|\.\.)([\\/]|$)') {
            throw 'STOP_OUTPUT_PATH_UNTRUSTED'
        }
        $rootPrefix = [IO.Path]::GetFullPath($ComfyOutputRoot).TrimEnd('\') + '\'
        $full = [IO.Path]::GetFullPath((Join-Path $ComfyOutputRoot $relpath))
        if (-not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $full -PathType Leaf)) {
            throw 'STOP_OUTPUT_FILE_NOT_FOUND'
        }
        $actual = Get-Item -LiteralPath $full
        if ($actual.Length -ne [long]$source.output_bytes -or
            (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne [string]$source.output_sha256) {
            throw 'STOP_OUTPUT_BYTES_OR_SHA_MISMATCH'
        }
        $action = [string]$task.positive_prompt
        if ($action.Length -gt 1000) { $action = $action.Substring(0, 1000) }
        $shots.Add([ordered]@{
            order = [int]$task.order
            shot_id = [string]$task.shot_id
            task_id = [string]$task.production_task_id
            relative_path = $relpath
            sha256 = [string]$source.output_sha256
            bytes = [long]$source.output_bytes
            expected_frames = [int]$task.frame_count
            expected_duration_ms = [int]$task.target_duration_ms
            action = $action
        })
    }
    if (@($shots | Select-Object -ExpandProperty shot_id -Unique).Count -ne 3 -or
        @($shots | Select-Object -ExpandProperty task_id -Unique).Count -ne 3) {
        throw 'STOP_DUPLICATE_SHOT_OR_TASK'
    }

    # ── Local tools      : use operator-owned ffmpeg/ffprobe; no download or model.
    $ffmpeg = Get-Command 'ffmpeg.exe' -ErrorAction Stop
    $ffprobe = Get-Command 'ffprobe.exe' -ErrorAction Stop
    $dotnet = Get-Command 'dotnet.exe' -ErrorAction Stop
    $project = Join-Path $PSScriptRoot 'PicotooPet.VisualReview.csproj'
    & $dotnet.Source build $project -c Release --nologo --verbosity quiet
    if ($LASTEXITCODE -ne 0) { throw 'STOP_VISUAL_REVIEW_BUILD_FAILED' }

    # ── Evidence output  : new private local directory, never inside Comfy.
    $parent = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\VisualReviewEvidence'
    $requestDir = Join-Path $parent 'requests'
    [void](New-Item -ItemType Directory -Path $requestDir -Force)
    $nonce = [guid]::NewGuid().ToString('N')
    $manifestPath = Join-Path $requestDir "$ProductionJobId-$nonce.json"
    $reviewDir = Join-Path $parent "review-$ProductionJobId-$nonce"
    $manifest = [ordered]@{
        schema_version = 'visual_review.input.v1'
        job_id = $ProductionJobId
        shots = @($shots.ToArray())
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $builtDll = Join-Path $PSScriptRoot 'bin\Release\net10.0\PicotooPet.VisualReview.dll'

    & $dotnet.Source $builtDll $manifestPath $ComfyOutputRoot $reviewDir $ffprobe.Source $ffmpeg.Source
    if ($LASTEXITCODE -ne 0) { throw 'STOP_VISUAL_REVIEW_UNVERIFIED' }

    $reportPath = Join-Path $reviewDir 'report.json'
    $sheetPath = Join-Path $reviewDir 'contact_sheet_3x3.png'
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'ADVISORY_REVIEW' -or
        -not (Test-Path -LiteralPath $sheetPath -PathType Leaf)) {
        throw 'STOP_NO_REVIEW_CONTACT_SHEET'
    }
    Write-Output 'CPU_VISUAL_EVIDENCE=READY_FOR_HUMAN_REVIEW'
    Write-Output "JOB_ID=$ProductionJobId"
    Write-Output 'SOURCE_SHOTS_SHA256_VERIFIED=3'
    Write-Output "CONTACT_SHEET_PATH=$sheetPath"
    Write-Output "REPORT_PATH=$reportPath"
    Write-Output 'VISUAL_ACCEPT=UNVERIFIED'
    Write-Output 'GPU_POST=0'
}
catch {
    # ── Privacy          : never print arbitrary HTTP/FFmpeg messages or secret data.
    $detail = [string]$_.Exception.Message
    $code = if ($detail -match '^STOP_[A-Z0-9_]{3,90}$') { $detail } else { 'STOP_UNCLASSIFIED_CHECK_FAILED' }
    Write-Output "CPU_VISUAL_EVIDENCE=$code"
    Write-Output 'VISUAL_ACCEPT=UNVERIFIED'
}
finally {
    $headers = $null
    $credential = $null
}
