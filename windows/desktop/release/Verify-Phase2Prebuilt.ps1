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

function Assert-SecureCoreAddress {
    param([Parameter(Mandatory)][string]$Url)

    # 校验与 Studio / Worker 一致：HTTPS 或本机环回 HTTP；旧局域网 HTTP 严格拒绝。
    $uri = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$uri) -or
        $null -eq $uri -or
        -not [string]::IsNullOrEmpty($uri.UserInfo) -or
        -not [string]::IsNullOrEmpty($uri.Query) -or
        -not [string]::IsNullOrEmpty($uri.Fragment) -or
        $uri.AbsolutePath -ne '/' -or
        ($uri.Scheme -ne 'https' -and
         -not ($uri.Scheme -eq 'http' -and $uri.IsLoopback))) {
        throw "禁止使用不安全 Mac Core 地址；请先建立本机 SSH 隧道或使用可信 HTTPS。"
    }
    return $uri.AbsoluteUri.TrimEnd('/')
}

$dataRoot     = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$currentPath  = Join-Path $dataRoot "current_version.json"
$reportsRoot  = Join-Path $dataRoot "reports"
$reportPath   = Join-Path $reportsRoot "phase2-windows-verification.json"
$settingsPath = Join-Path $env:LOCALAPPDATA "PicotooPetV2\Desktop\settings.json"
$baseUrl      = "http://127.0.0.1:18766"
$exitCode     = 2
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

try {
    if (-not (Test-Path -LiteralPath $currentPath)) { throw "尚未安装 Phase 2 Windows Desktop。" }
    $current      = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    $manifestPath = Join-Path $current.path "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "当前版本缺少 release-manifest.json。" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-ManifestFiles -Manifest $manifest -Root $current.path

    # 验证安装后的真实独立 Worker EXE，不启动桥接服务、不碰 GPU。
    # 该检查不能证明模型/Comfy 已部署；只证明本机运行时文件可信且可执行。
    $workerPath = Join-Path $current.path "tools\worker\PicotooPet.Worker\PicotooPet.Worker.exe"
    if (-not (Test-Path -LiteralPath $workerPath)) {
        throw "安装不完整：缺少经清单验证的 Windows Worker。"
    }
    $workerOutput = & $workerPath --package-self-test
    if ($LASTEXITCODE -ne 0) { throw "安装后的 Worker 自检退出码非零：$LASTEXITCODE" }
    $workerCheck = ($workerOutput -join "`n") | ConvertFrom-Json
    if (
        $workerCheck.contract -ne "picotoo.worker-bundled-runtime.v1" -or
        $workerCheck.packaged -ne $true -or
        $workerCheck.qc_importable -ne $true -or
        $workerCheck.edit_importable -ne $true -or
        $workerCheck.review_importable -ne $true -or
        $workerCheck.review_template_present -ne $true -or
        $workerCheck.gpu_started -ne $false -or
        $workerCheck.lease_attempted -ne $false
    ) {
        throw "安装后的 Worker 不能证明已有 QC/剪辑/批次导入和 GPU HOLD 自检。"
    }

    if (Test-Path -LiteralPath $settingsPath) {
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        if (-not [string]::IsNullOrWhiteSpace([string]$settings.macBaseUrl)) {
            $candidate = [Uri]$settings.macBaseUrl
            if ($candidate.IsAbsoluteUri) { $baseUrl = $candidate.AbsoluteUri.TrimEnd('/') }
        }
    }

    # 诊断工具绝不绕过 Studio 的网络门禁，拒绝把设备令牌发往旧局域网 HTTP。
    $baseUrl = Assert-SecureCoreAddress -Url $baseUrl

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
