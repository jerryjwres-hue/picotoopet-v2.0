# Phase 2 Windows 预编译安装器；用户电脑不执行源码编译、不安装 SDK。
[CmdletBinding()]
param(
    [string]$PackageRoot = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$dataRoot       = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$versionsRoot   = Join-Path $dataRoot "versions"
$reportsRoot    = Join-Path $dataRoot "reports"
$logsRoot       = Join-Path $dataRoot "logs"
$currentPath    = Join-Path $dataRoot "current_version.json"
$previousPath   = Join-Path $dataRoot "previous_version.json"
$statePath      = Join-Path $dataRoot "install-state.json"
$manifestPath   = Join-Path $PackageRoot "release-manifest.json"
$payloadRoot    = Join-Path $PackageRoot "payload"
$timestamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$reportPath     = Join-Path $reportsRoot "phase2-prebuilt-install-$timestamp.json"
$logPath        = Join-Path $logsRoot "phase2-prebuilt-install-$timestamp.log"
$installMutex   = [System.Threading.Mutex]::new($false, "Global\PicotooPetV2.Phase2Installer")
$mutexOwned     = $false
$previousCurrent  = $null
$previousPrevious = $null
$activationStarted = $false
$hadCurrentPointer  = Test-Path -LiteralPath $currentPath
$hadPreviousPointer = Test-Path -LiteralPath $previousPath
$stagingPath        = $null
$finalPath          = $null

New-Item -ItemType Directory -Path $versionsRoot, $reportsRoot, $logsRoot -Force | Out-Null

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Value
    )

    # Windows PowerShell 5.1 默认编码不稳定；所有状态文件固定为 UTF-8 无 BOM。
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    # 同卷临时文件原子替换，避免断电留下半个版本指针或状态文件。
    $temporary = "$Path.tmp"
    Write-Utf8NoBom -Path $temporary -Value ($Value | ConvertTo-Json -Depth 20)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Write-InstallLog {
    param(
        [Parameter(Mandatory)][string]$Level,
        [Parameter(Mandatory)][string]$Message
    )

    # 安装日志不记录令牌和业务数据，只记录本地安装阶段与错误摘要。
    $line = "{0}`t{1}`t{2}" -f (Get-Date).ToUniversalTime().ToString("o"), $Level, $Message
    [System.IO.File]::AppendAllText($logPath, $line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

function Write-InstallProgress {
    param(
        [Parameter(Mandatory)][ValidateRange(0, 100)][int]$Percent,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Detail
    )

    # 控制台、Write-Progress 和 install-state.json 同步更新，用户不再依赖任务管理器猜状态。
    $state = [ordered]@{
        schema_version = "2.2.0"
        updated_at     = (Get-Date).ToUniversalTime().ToString("o")
        status         = if ($Percent -eq 100) { "completed" } else { "running" }
        percent        = $Percent
        stage          = $Stage
        detail         = $Detail
        report         = $reportPath
        log            = $logPath
    }
    Write-JsonAtomic -Value $state -Path $statePath
    Write-Progress -Activity "Picotoo Pet V2 Windows Desktop" -Status "$Stage - $Detail" -PercentComplete $Percent
    Write-Host ("[{0,3}%] {1} - {2}" -f $Percent, $Stage, $Detail)
    Write-InstallLog -Level "INFO" -Message "$Percent% | $Stage | $Detail"
}

function Assert-ManifestFiles {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$Root
    )

    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or $relative.Contains("..") -or [System.IO.Path]::IsPathRooted($relative)) {
            throw "发布清单包含非法路径：$relative"
        }
        $path = Join-Path $Root ($relative -replace '/', '\\')
        if (-not (Test-Path -LiteralPath $path)) { throw "发布文件缺失：$relative" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) { throw "发布文件 SHA-256 不一致：$relative" }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "发布文件大小不一致：$relative"
        }
    }
}

function Get-PicotooShortcutPaths {
    # 开始菜单和开机启动入口由同一个函数集中管理，避免版本指针不一致。
    return @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Picotoo Pet AI.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Picotoo Pet AI.lnk")
    )
}

function Set-PicotooShortcuts {
    param([Parameter(Mandatory)][string]$Executable)

    # 快捷方式只指向已通过清单哈希校验的版本目录。
    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcutPath in Get-PicotooShortcutPaths) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $Executable
        $shortcut.WorkingDirectory = Split-Path -Parent $Executable
        $shortcut.Description      = "Picotoo Pet V2 双机 AI 控制面板"
        $shortcut.Save()
    }
}

function Remove-PicotooShortcuts {
    foreach ($shortcutPath in Get-PicotooShortcutPaths) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    }
}

function Restore-PreviousActivation {
    # 激活失败时同时恢复当前指针、上一版本指针和快捷方式。
    if ($null -ne $previousCurrent) {
        Write-JsonAtomic -Value $previousCurrent -Path $currentPath
        Set-PicotooShortcuts -Executable ([string]$previousCurrent.executable)
        Start-Process -FilePath $previousCurrent.executable -WorkingDirectory $previousCurrent.path
    }
    else {
        Remove-Item -LiteralPath $currentPath -Force -ErrorAction SilentlyContinue
        Remove-PicotooShortcuts
    }

    if ($hadPreviousPointer -and $null -ne $previousPrevious) {
        Write-JsonAtomic -Value $previousPrevious -Path $previousPath
    }
    else {
        Remove-Item -LiteralPath $previousPath -Force -ErrorAction SilentlyContinue
    }
}

$report = [ordered]@{
    schema_version       = "2.2.0"
    generated_at         = (Get-Date).ToUniversalTime().ToString("o")
    status               = "running"
    version              = $null
    install_path         = $null
    log                  = $logPath
    executable_sha256    = $null
    diagnostic_sha256    = $null
    source_build_on_user_pc = $false
    error                = $null
}

$exitCode = 1
try {
    try {
        $mutexOwned = $installMutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $mutexOwned = $true
    }
    if (-not $mutexOwned) { throw "已有 Phase 2 安装或回滚正在运行。" }

    Write-InstallProgress -Percent 5 -Stage "校验安装包" -Detail "读取预编译发布清单"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "安装包缺少 release-manifest.json。" }
    if (-not (Test-Path -LiteralPath $payloadRoot))  { throw "安装包缺少 payload 目录。" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.release_type -ne "prebuilt") { throw "安装包不是预编译发布类型。" }
    if ([string]$manifest.target -ne "win-x64")       { throw "安装包目标不是 win-x64。" }
    if ([string]$manifest.version -notmatch '^[A-Za-z0-9._-]+$') { throw "安装包版本号非法。" }
    $versionId = [string]$manifest.version
    $report.version      = $versionId
    $finalPath           = Join-Path $versionsRoot $versionId
    $stagingPath         = Join-Path $versionsRoot ".staging-$versionId-$PID"
    $report.install_path = $finalPath
    Assert-ManifestFiles -Manifest $manifest -Root $payloadRoot

    Write-InstallProgress -Percent 20 -Stage "检查当前版本" -Detail "保存可回滚版本指针"
    if ($hadCurrentPointer) {
        $previousCurrent = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    }
    if ($hadPreviousPointer) {
        $previousPrevious = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
    }

    if (-not (Test-Path -LiteralPath $finalPath)) {
        Write-InstallProgress -Percent 35 -Stage "安装预编译文件" -Detail "复制到版本暂存目录"
        if (Test-Path -LiteralPath $stagingPath) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force
        }
        New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
        Copy-Item -Path (Join-Path $payloadRoot "*") -Destination $stagingPath -Recurse -Force
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stagingPath "release-manifest.json") -Force

        Write-InstallProgress -Percent 55 -Stage "校验已安装文件" -Detail "重新计算 SHA-256 与文件大小"
        Assert-ManifestFiles -Manifest $manifest -Root $stagingPath
        Move-Item -LiteralPath $stagingPath -Destination $finalPath
    }
    else {
        Write-InstallProgress -Percent 55 -Stage "复用已验证版本" -Detail "版本目录已存在，重新校验"
        Assert-ManifestFiles -Manifest $manifest -Root $finalPath
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $finalPath "release-manifest.json") -Force
    }

    $executable = Join-Path $finalPath "Picotoo Pet AI.exe"
    $diagnostic = Join-Path $finalPath "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    $appEntry   = $manifest.files | Where-Object { [string]$_.path -eq "Picotoo Pet AI.exe" } | Select-Object -First 1
    $diagEntry  = $manifest.files | Where-Object { [string]$_.path -eq "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe" } | Select-Object -First 1
    if ($null -eq $appEntry -or $null -eq $diagEntry) { throw "发布清单缺少主程序或诊断程序。" }

    Write-InstallProgress -Percent 70 -Stage "激活新版本" -Detail "原子更新版本指针与快捷方式"
    $activationStarted = $true
    if ($null -ne $previousCurrent) {
        Write-JsonAtomic -Value $previousCurrent -Path $previousPath
    }
    $currentPointer = [ordered]@{
        version             = $versionId
        path                = $finalPath
        executable          = $executable
        activated_at        = (Get-Date).ToUniversalTime().ToString("o")
        executable_sha256   = [string]$appEntry.sha256
        diagnostic_sha256   = [string]$diagEntry.sha256
    }
    Write-JsonAtomic -Value $currentPointer -Path $currentPath
    Set-PicotooShortcuts -Executable $executable

    Write-InstallProgress -Percent 85 -Stage "启动应用" -Detail "检查新进程能否保持运行"
    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    $process = Start-Process -FilePath $executable -WorkingDirectory $finalPath -PassThru
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) { throw "Picotoo Pet AI 启动后立即退出，退出码 $($process.ExitCode)。" }

    $report.status            = "pass"
    $report.executable_sha256 = [string]$appEntry.sha256
    $report.diagnostic_sha256 = [string]$diagEntry.sha256
    Write-JsonAtomic -Value $report -Path $reportPath
    Write-InstallProgress -Percent 100 -Stage "安装完成" -Detail "预编译版本已安装并启动"
    $exitCode = 0
}
catch {
    $primaryError = $_.Exception.Message
    $restoreError = $null
    if ($activationStarted) {
        try { Restore-PreviousActivation } catch { $restoreError = $_.Exception.Message }
    }
    if ($null -ne $stagingPath -and (Test-Path -LiteralPath $stagingPath)) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    $report.status = "fail"
    $report.error  = if ($null -eq $restoreError) {
        $primaryError
    } else {
        "$primaryError | 自动恢复失败：$restoreError"
    }
    Write-JsonAtomic -Value $report -Path $reportPath
    Write-InstallLog -Level "ERROR" -Message $report.error
    $failedState = [ordered]@{
        schema_version = "2.2.0"
        updated_at     = (Get-Date).ToUniversalTime().ToString("o")
        status         = "fail"
        percent        = 100
        stage          = "安装失败"
        detail         = $report.error
        report         = $reportPath
        log            = $logPath
    }
    Write-JsonAtomic -Value $failedState -Path $statePath
    Write-Host "[FAIL] $($report.error)" -ForegroundColor Red
}
finally {
    Write-Progress -Activity "Picotoo Pet V2 Windows Desktop" -Completed
    if ($mutexOwned) { $installMutex.ReleaseMutex() }
    $installMutex.Dispose()
    if (Test-Path -LiteralPath $reportPath) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
