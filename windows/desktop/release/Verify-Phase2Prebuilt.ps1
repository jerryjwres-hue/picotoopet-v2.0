# Phase 2 Windows 预编译安装验证；校验文件、进程和真实双机链路。
[CmdletBinding()]
param(
    [int]$RestSamples = 500,
    [int]$TaskSamples = 500,
    [int]$SocketSamples = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

    # Start-Process 会重新拼接参数；包含空格或引号时必须显式加引号。
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Write-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Value)

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Read-JsonUtf8 {
    param([Parameter(Mandatory)][string]$Path)

    # 机器 JSON 固定按严格 UTF-8 读取，绕过 Windows PowerShell 5.1 的区域默认编码。
    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $json = [System.IO.File]::ReadAllText($Path, $encoding)
        return ($json | ConvertFrom-Json)
    }
    catch {
        throw "JSON 解析失败：$Path | $($_.Exception.Message)"
    }
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Path)

    $temporary = "$Path.tmp"
    Write-Utf8NoBom -Path $temporary -Value ($Value | ConvertTo-Json -Depth 20)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-ManifestFiles {
    param([Parameter(Mandatory)]$Manifest, [Parameter(Mandatory)][string]$Root)

    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        $path     = Join-Path $Root ($relative -replace '/', '\\')
        if (-not (Test-Path -LiteralPath $path)) { throw "当前版本文件缺失：$relative" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) { throw "当前版本 SHA-256 不一致：$relative" }
    }
}

$dataRoot     = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$currentPath  = Join-Path $dataRoot "current_version.json"
$reportsRoot  = Join-Path $dataRoot "reports"
$reportPath   = Join-Path $reportsRoot "phase2-windows-verification.json"
$settingsPath = Join-Path $env:LOCALAPPDATA "PicotooPetV2\Desktop\settings.json"
$baseUrl      = "http://127.0.0.1:8766"
$exitCode     = 2
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

try {
    if (-not (Test-Path -LiteralPath $currentPath)) { throw "尚未安装 Phase 2 Windows Desktop。" }
    $current      = Read-JsonUtf8 -Path $currentPath
    $manifestPath = Join-Path $current.path "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "当前版本缺少 release-manifest.json。" }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    Assert-ManifestFiles -Manifest $manifest -Root $current.path

    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Read-JsonUtf8 -Path $settingsPath
        if (-not [string]::IsNullOrWhiteSpace([string]$settings.macBaseUrl)) {
            $candidate = [Uri]$settings.macBaseUrl
            if ($candidate.IsAbsoluteUri) { $baseUrl = $candidate.AbsoluteUri.TrimEnd('/') }
        }
    }

    $executable = [string]$current.executable
    $diagnostic = Join-Path $current.path "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    if ($null -eq (Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $executable -WorkingDirectory $current.path
        Start-Sleep -Seconds 2
    }

    $arguments = @(
        "--base-url", $baseUrl,
        "--output", $reportPath,
        "--rest-samples", [string]$RestSamples,
        "--task-samples", [string]$TaskSamples,
        "--socket-samples", [string]$SocketSamples
    )
    $argumentLine = ($arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join ' '
    $process = Start-Process -FilePath $diagnostic -ArgumentList $argumentLine `
        -WorkingDirectory (Split-Path -Parent $diagnostic) -WindowStyle Hidden -Wait -PassThru
    $exitCode = $process.ExitCode
    if (-not (Test-Path -LiteralPath $reportPath)) { throw "诊断程序未生成报告。" }
}
catch {
    $fallback = [ordered]@{
        schema_version = "2.2.0"
        generated_at   = (Get-Date).ToUniversalTime().ToString("o")
        status         = "fail"
        environment    = [ordered]@{ base_url = $baseUrl }
        metrics        = [ordered]@{}
        errors         = @("VERIFIER_FAILURE | $($_.Exception.GetType().Name): $($_.Exception.Message)")
    }
    Write-JsonAtomic -Value $fallback -Path $reportPath
    $exitCode = 2
}
finally {
    if (Test-Path -LiteralPath $reportPath) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
