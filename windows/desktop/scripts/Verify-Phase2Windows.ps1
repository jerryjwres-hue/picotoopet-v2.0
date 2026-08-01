# Phase 2 Windows Desktop 实机验证；无论成功或失败都生成统一机器可读报告。
[CmdletBinding()]
param(
    [int]$RestSamples = 500,
    [int]$TaskSamples = 500,
    [int]$SocketSamples = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)
    # Start-Process 会重新拼接参数；包含空格或引号时必须显式转义。
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Write-JsonAtomic {
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Path)
    # 同卷临时文件原子替换，避免断电或进程终止留下半个 JSON。
    $temporary = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function New-VerificationReport {
    param(
        [Parameter(Mandatory)][ValidateSet("pass", "fail", "incomplete")][string]$Status,
        [Parameter(Mandatory)][string]$BaseUrl,
        [string[]]$Errors = @()
    )
    # 失败路径与成功路径共用同一 Schema，方便桌面面板和自动验收稳定解析。
    return [ordered]@{
        schema_version       = "2.2.0"
        generated_at         = (Get-Date).ToUniversalTime().ToString("o")
        status               = $Status
        environment          = [ordered]@{
            machine          = if ([string]::IsNullOrWhiteSpace($env:COMPUTERNAME)) { "unknown-windows" } else { $env:COMPUTERNAME }
            operating_system = [System.Environment]::OSVersion.VersionString
            architecture     = if ([string]::IsNullOrWhiteSpace($env:PROCESSOR_ARCHITECTURE)) { "unknown" } else { $env:PROCESSOR_ARCHITECTURE }
            base_url         = $BaseUrl
            rest_samples     = [Math]::Max(1, $RestSamples)
            task_samples     = [Math]::Max(1, $TaskSamples)
            socket_samples   = [Math]::Max(1, $SocketSamples)
        }
        metrics              = [ordered]@{}
        last_sequence        = $null
        sample_task_first_id = $null
        sample_task_last_id  = $null
        errors               = @($Errors)
    }
}

$dataRoot     = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$currentPath  = Join-Path $dataRoot "current_version.json"
$reportsRoot  = Join-Path $dataRoot "reports"
$reportPath   = Join-Path $reportsRoot "phase2-windows-verification.json"
$settingsPath = Join-Path $env:LOCALAPPDATA "PicotooPetV2\Desktop\settings.json"
$baseUrl      = "http://192.168.1.161:8766"
$exitCode     = 2
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

try {
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
            if (-not [string]::IsNullOrWhiteSpace([string]$settings.macBaseUrl)) {
                $candidate = [Uri]$settings.macBaseUrl
                if (-not $candidate.IsAbsoluteUri) { throw "Mac Base URL 必须是绝对地址。" }
                $baseUrl = $candidate.AbsoluteUri.TrimEnd('/')
            }
        }
        catch {
            # 设置文件损坏时保留冻结地址；真正连接结果由诊断报告记录。
        }
    }

    if (-not (Test-Path -LiteralPath $currentPath)) {
        throw [System.IO.FileNotFoundException]::new("尚未安装 Phase 2 Windows Desktop。")
    }

    $current      = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    $versionPath  = Join-Path $current.path "version.json"
    if (-not (Test-Path -LiteralPath $versionPath)) { throw "当前版本清单不存在。" }
    $version      = Get-Content -LiteralPath $versionPath -Raw | ConvertFrom-Json
    $executable   = [string]$current.executable
    $diagnostic   = Join-Path $current.path "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    if (-not (Test-Path -LiteralPath $executable)) { throw "当前版本主程序不存在。" }
    if (-not (Test-Path -LiteralPath $diagnostic)) { throw "当前版本 PicotooPet.Desktop.Diagnostics 不存在。" }

    $actualExecutableHash = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $actualDiagnosticHash = (Get-FileHash -LiteralPath $diagnostic -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualExecutableHash -ne [string]$version.executable_sha256) {
        throw "主程序 SHA-256 与版本清单不一致。"
    }
    if ($actualDiagnosticHash -ne [string]$version.diagnostic_sha256) {
        throw "诊断程序 SHA-256 与版本清单不一致。"
    }

    if ($null -eq (Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $executable -WorkingDirectory $current.path
        Start-Sleep -Milliseconds 800
    }

    $arguments = @(
        "--base-url", $baseUrl,
        "--output", $reportPath,
        "--rest-samples", [string]$RestSamples,
        "--task-samples", [string]$TaskSamples,
        "--socket-samples", [string]$SocketSamples
    )
    $argumentLine = ($arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join " "
    $process = Start-Process -FilePath $diagnostic -ArgumentList $argumentLine `
        -WorkingDirectory (Split-Path -Parent $diagnostic) -WindowStyle Hidden -Wait -PassThru
    $exitCode = $process.ExitCode

    if (-not (Test-Path -LiteralPath $reportPath)) {
        throw "诊断进程已结束，但没有生成验证报告。"
    }
}
catch {
    $status = if ($_.Exception -is [System.IO.FileNotFoundException]) { "incomplete" } else { "fail" }
    $fallback = New-VerificationReport -Status $status -BaseUrl $baseUrl -Errors @(
        "VERIFIER_FAILURE | $($_.Exception.GetType().Name): $($_.Exception.Message)"
    )
    Write-JsonAtomic -Value $fallback -Path $reportPath
    $exitCode = 2
}
finally {
    # 即使诊断失败也打开同一路径，用户无需寻找日志或猜测错误位置。
    if (Test-Path -LiteralPath $reportPath) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
