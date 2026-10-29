#requires -Version 5.1
<#
.SYNOPSIS
    P0-Q2 #143 read-only final-video triage. No GUI, Worker, Comfy POST, or writes.
.DESCRIPTION
    -JobId defaults to the original first-film Production Job.
    Optional -MacCoreUrl performs only two authenticated GET requests and prompts
    for a bearer token without placing it on the command line or in the output.
    Never interpret existing WebMs or a settled journal as a PASS production package.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string]$JobId = '64695948-fb1a-4793-815f-3f6ad4d4d536',
    [string]$MacCoreUrl = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Match C004's SHA256(job id), lower-case prefix and fixed managed paths. ──
$localData = [Environment]::GetFolderPath('LocalApplicationData')
$bytes = [Text.Encoding]::UTF8.GetBytes($JobId)
$sha = [Security.Cryptography.SHA256]::Create()
try { $hex = ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
$stem = 'final-' + $hex.Substring(0, 32)
$finalDir = Join-Path $localData 'PicotooPet\FinalVideos'
$finalFile = Join-Path $finalDir ($stem + '.mp4')
$manifest = Join-Path $finalDir ($stem + '.final-video.json')
$receiptDir = Join-Path $localData 'PicotooPet\PostProduction\DeliveryReceipts\v1'
$projectionDir = Join-Path $localData 'PicotooPet\PostProduction\VerifiedGoals\v1'
$workerLog = Join-Path $localData 'PicotooPetV2\Desktop\logs\media-worker.log'

function Test-RegularFile([string]$path) {
    # ── A link/zero-byte file is not valid delivery evidence. ──
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $file = Get-Item -LiteralPath $path -Force
    return ($file.Length -gt 0 -and -not ($file.Attributes -band [IO.FileAttributes]::ReparsePoint))
}
function Count-OrdinaryJson([string]$path) {
    # ── A directory count is not a job-specific QA approval. ──
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { return 0 }
    return @(
        Get-ChildItem -LiteralPath $path -Filter '*.json' -File -ErrorAction Stop |
        Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }
    ).Count
}

Write-Output "JOB_ID=$JobId"
Write-Output "C004_EXPECTED_FILENAME=$stem.mp4"
Write-Output "C004_MP4_PRESENT=$(Test-RegularFile $finalFile)"
Write-Output "C004_MANIFEST_PRESENT=$(Test-RegularFile $manifest)"
Write-Output "C011_RECEIPT_DIRECTORY_JSON_COUNT=$(Count-OrdinaryJson $receiptDir)"
Write-Output "GUI_PROJECTION_DIRECTORY_JSON_COUNT=$(Count-OrdinaryJson $projectionDir)"
Write-Output 'RECEIPT_AND_PROJECTION_COUNTS_ARE_NOT_JOB_SPECIFIC=TRUE'
Write-Output "FFMPEG_ON_PATH=$([bool](Get-Command ffmpeg.exe -ErrorAction SilentlyContinue))"
Write-Output "FFPROBE_ON_PATH=$([bool](Get-Command ffprobe.exe -ErrorAction SilentlyContinue))"

if (Test-RegularFile $finalFile) {
    # ── Hashing is read-only; this does not replace C010A full decode and QA. ──
    $file = Get-Item -LiteralPath $finalFile
    Write-Output "C004_MP4_BYTES=$($file.Length)"
    Write-Output "C004_MP4_SHA256=$((Get-FileHash -LiteralPath $finalFile -Algorithm SHA256).Hash.ToLowerInvariant())"
}
if (Test-RegularFile $manifest) {
    try {
        $record = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        Write-Output "C004_MANIFEST_JOB_MATCH=$($record.production_job_id -ceq $JobId)"
        Write-Output "C004_MANIFEST_SHA_MATCH=$($record.final_sha256 -eq $(if (Test-RegularFile $finalFile) { (Get-FileHash -LiteralPath $finalFile -Algorithm SHA256).Hash.ToLowerInvariant() } else { '' }))"
    } catch { Write-Output 'C004_MANIFEST_PARSE=FAILED' }
}
if (Test-RegularFile $workerLog) {
    # ── Print only sanitized known error codes, never raw prompts, paths or tokens. ──
    $known = 'COMFY_DATA_ROOT_NOT_FOUND|COMFY_OUTPUT_ROOT_NOT_FOUND|FINAL_VIDEO_[A-Z_]+|C011_[A-Z_]+|P0 journal'
    $matches = @(Select-String -LiteralPath $workerLog -Pattern $known -AllMatches -ErrorAction SilentlyContinue |
        Select-Object -Last 12)
    Write-Output "WORKER_LOG_KNOWN_ERROR_LINE_COUNT=$($matches.Count)"
    foreach ($item in $matches) {
        $codes = @([regex]::Matches($item.Line, 'COMFY_DATA_ROOT_NOT_FOUND|COMFY_OUTPUT_ROOT_NOT_FOUND|FINAL_VIDEO_[A-Z_]+|C011_[A-Z_]+') |
            ForEach-Object { $_.Value } | Select-Object -Unique)
        foreach ($code in $codes) { Write-Output "WORKER_LOG_ERROR_CODE=$code" }
    }
} else {
    Write-Output 'WORKER_LOG=NOT_FOUND'
}

if (-not [string]::IsNullOrWhiteSpace($MacCoreUrl)) {
    # ── Only exact authenticated GETs; no bearer token is saved or printed. ──
    $root = $null
    if (-not [Uri]::TryCreate($MacCoreUrl, [UriKind]::Absolute, [ref]$root) -or
        $root.Scheme -notin @('http', 'https') -or $root.UserInfo -ne '') {
        throw 'MAC_CORE_URL_INVALID'
    }
    $secure = Read-Host 'Mac Core Bearer token (hidden; only GET)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    try {
        $base = $MacCoreUrl.TrimEnd('/')
        $uri = $base + '/api/v1/production/jobs/' + $JobId
        $header = @{ Authorization = ('Bearer ' + $token) }
        $job = Invoke-RestMethod -Uri $uri -Method Get -Headers $header -MaximumRedirection 0 -TimeoutSec 10
        Write-Output "CORE_PRODUCTION_STATUS=$($job.status)"
        Write-Output "CORE_PLAN_DIGEST_PRESENT=$([bool]$job.plan_digest)"
        $package = Invoke-RestMethod -Uri ($uri + '/package') -Method Get -Headers $header -MaximumRedirection 0 -TimeoutSec 10
        Write-Output "CORE_PACKAGE_PRESENT=$($null -ne $package)"
        if ($null -ne $package) {
            Write-Output "CORE_PACKAGE_JOB_MATCH=$($package.production_job_id -ceq $JobId)"
            Write-Output "CORE_PACKAGE_QA_OUTCOME=$($package.quality_outcome)"
            Write-Output "CORE_PACKAGE_OUTPUT_COUNT=$(@($package.manifest.outputs).Count)"
        }
    } catch {
        # ── Authentication/network failures must remain UNVERIFIED, not NOT_FOUND. ──
        Write-Output 'CORE_GET=UNVERIFIED_AUTH_OR_NETWORK'
    } finally {
        $token = $null
        $header = $null
    }
} else {
    Write-Output 'CORE_PRODUCTION_STATUS=UNVERIFIED_NOT_QUERIED'
    Write-Output 'CORE_PACKAGE=UNVERIFIED_NOT_QUERIED'
}
Write-Output 'C011_QA_PASS=UNVERIFIED_UNLESS_EXACT_IMMUTABLE_RECEIPT_VALIDATED'
Write-Output 'NO_GPU_OR_MUTATING_REQUESTS=TRUE'
