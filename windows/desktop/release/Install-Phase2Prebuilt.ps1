# Phase 2 Windows 预编译安装器；用户电脑不执行源码编译、不安装 SDK。
[CmdletBinding()]
param(
    [string]$PackageRoot = $PSScriptRoot,
    [string]$DataRoot = "",
    [string]$DesktopDirectory = "",
    [switch]$PreflightOnly,
    [switch]$ActivationSelfTest,
    [switch]$SuppressReportOpen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$commonScript = Join-Path $PSScriptRoot "Phase2Prebuilt.Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript -PathType Leaf)) {
    throw "安装包缺少 Phase2Prebuilt.Common.ps1。"
}
. $commonScript

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)

$dataRoot         = $DataRoot
$versionsRoot     = Join-Path $dataRoot "versions"
$reportsRoot      = Join-Path $dataRoot "reports"
$logsRoot         = Join-Path $dataRoot "logs"
$currentPath      = Join-Path $dataRoot "current_version.json"
$previousPath     = Join-Path $dataRoot "previous_version.json"
$statePath        = Join-Path $dataRoot "install-state.json"
$manifestPath     = Join-Path $PackageRoot "release-manifest.json"
$payloadRoot      = Join-Path $PackageRoot "payload"
$timestamp        = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$reportPath       = Join-Path $reportsRoot "phase2-prebuilt-install-$timestamp.json"
$logPath          = Join-Path $logsRoot "phase2-prebuilt-install-$timestamp.log"
$activationReport = Join-Path $reportsRoot "phase2-prebuilt-activation-$timestamp.json"
$installMutex     = [System.Threading.Mutex]::new($false, "Global\PicotooPetV2.Phase2Installer")
$mutexOwned       = $false
$previousCurrent  = $null
$previousPrevious = $null
$activationStarted = $false
$hadCurrentPointer  = Test-Path -LiteralPath $currentPath
$hadPreviousPointer = Test-Path -LiteralPath $previousPath
$stagingPath        = $null
$finalPath          = $null
$productVersion     = ""
$preActivationShortcutState = @()

New-Item -ItemType Directory -Path $versionsRoot, $reportsRoot, $logsRoot -Force | Out-Null

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Value
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Read-JsonUtf8 {
    param([Parameter(Mandatory)][string]$Path)

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
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $temporary = "$Path.tmp"
    Write-Utf8NoBom -Path $temporary -Value ($Value | ConvertTo-Json -Depth 30)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Write-InstallLog {
    param(
        [Parameter(Mandatory)][string]$Level,
        [Parameter(Mandatory)][string]$Message
    )

    $line = "{0}`t{1}`t{2}" -f (Get-Date).ToUniversalTime().ToString("o"), $Level, $Message
    [System.IO.File]::AppendAllText(
        $logPath,
        $line + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false))
}

function Write-InstallProgress {
    param(
        [Parameter(Mandatory)][ValidateRange(0, 100)][int]$Percent,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$Detail
    )

    $state = [ordered]@{
        schema_version = "2.3.0"
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
        if ([string]::IsNullOrWhiteSpace($relative) -or
            $relative.Contains("..") -or
            [System.IO.Path]::IsPathRooted($relative)) {
            throw "发布清单包含非法路径：$relative"
        }
        $path = Join-Path $Root ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "发布文件缺失：$relative"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) {
            throw "发布文件 SHA-256 不一致：$relative"
        }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "发布文件大小不一致：$relative"
        }
    }
}

function Read-InstalledProductVersion {
    param([Parameter(Mandatory)][string]$Root)

    $versionFile = Join-Path $Root "product-version.txt"
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
        throw "版本目录缺少 product-version.txt：$Root"
    }
    $value = [System.IO.File]::ReadAllText(
        $versionFile,
        [System.Text.UTF8Encoding]::new($false, $true)).Trim()
    return Assert-PicotooProductVersion -ProductVersion $value
}

function Invoke-ActivationCheck {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [switch]$SelfTest
    )

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    if ($SelfTest) {
        $arguments = @("--self-test", "--self-test-output", $activationReport)
        $argumentLine = ($arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join ' '
        $process = Start-Process -FilePath $Executable -ArgumentList $argumentLine `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "激活自检失败，退出码 $($process.ExitCode)。"
        }
        if (-not (Test-Path -LiteralPath $activationReport -PathType Leaf)) {
            throw "激活自检未生成报告。"
        }
        $selfTestReport = Read-JsonUtf8 -Path $activationReport
        if ([string]$selfTestReport.status -ne "pass") {
            throw "激活自检报告不是 pass。"
        }
        if ([string]$selfTestReport.product_version -ne $productVersion) {
            throw "激活自检产品版本不一致：$($selfTestReport.product_version)"
        }
        return [pscustomobject][ordered]@{
            mode        = "self-test"
            status      = "pass"
            report      = $activationReport
            process_id  = $process.Id
        }
    }

    $process = Start-Process -FilePath $Executable -WorkingDirectory $WorkingDirectory -PassThru
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) {
        throw "Picotoo Pet AI 启动后立即退出，退出码 $($process.ExitCode)。"
    }
    return [pscustomobject][ordered]@{
        mode        = "interactive"
        status      = "pass"
        report      = $null
        process_id  = $process.Id
    }
}

function Restore-PreviousActivation {
    if ($null -ne $previousCurrent) {
        Write-JsonAtomic -Value $previousCurrent -Path $currentPath
    }
    else {
        Remove-Item -LiteralPath $currentPath -Force -ErrorAction SilentlyContinue
    }

    $restoredState = Restore-PicotooManagedShortcutSnapshot `
        -ShortcutState $preActivationShortcutState `
        -DesktopDirectory $DesktopDirectory
    $report.recovery_shortcuts = [ordered]@{
        restore_mode = "pre-activation-snapshot"
        shortcut_state = @($restoredState)
    }

    if ($null -ne $previousCurrent) {
        Invoke-ActivationCheck `
            -Executable ([string]$previousCurrent.executable) `
            -WorkingDirectory ([string]$previousCurrent.path) `
            -SelfTest:$ActivationSelfTest | Out-Null
    }

    if ($hadPreviousPointer -and $null -ne $previousPrevious) {
        Write-JsonAtomic -Value $previousPrevious -Path $previousPath
    }
    else {
        Remove-Item -LiteralPath $previousPath -Force -ErrorAction SilentlyContinue
    }
}

$report = [ordered]@{
    schema_version           = "2.3.0"
    generated_at             = (Get-Date).ToUniversalTime().ToString("o")
    status                   = "running"
    version                  = $null
    product_version          = $null
    install_path             = $null
    data_root                = $dataRoot
    log                      = $logPath
    executable_sha256        = $null
    diagnostic_sha256        = $null
    desktop_shortcut         = $null
    desktop_shortcut_created = $false
    shortcut_paths           = $null
    shortcut_state           = @()
    shortcuts_verified       = $false
    activation               = $null
    recovery_shortcuts       = $null
    source_build_on_user_pc  = $false
    error                    = $null
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
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "安装包缺少 release-manifest.json。"
    }
    if (-not (Test-Path -LiteralPath $payloadRoot -PathType Container)) {
        throw "安装包缺少 payload 目录。"
    }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    if ([string]$manifest.release_type -ne "prebuilt") { throw "安装包不是预编译发布类型。" }
    if ([string]$manifest.target -ne "win-x64")       { throw "安装包目标不是 win-x64。" }
    if ([string]$manifest.version -notmatch '^[A-Za-z0-9._-]+$') {
        throw "安装包版本号非法。"
    }
    if (-not ($manifest.PSObject.Properties.Name -contains "product_version")) {
        throw "发布清单缺少 product_version。"
    }
    $productVersion = Assert-PicotooProductVersion -ProductVersion ([string]$manifest.product_version)
    if ($manifest.PSObject.Properties.Name -contains "user_install_allowed" -and
        -not [bool]$manifest.user_install_allowed) {
        throw "发布清单不允许用户安装。"
    }

    $versionId              = [string]$manifest.version
    $report.version         = $versionId
    $report.product_version = $productVersion
    $finalPath              = Join-Path $versionsRoot $versionId
    $stagingPath            = Join-Path $versionsRoot ".staging-$versionId-$PID"
    $report.install_path    = $finalPath
    Assert-ManifestFiles -Manifest $manifest -Root $payloadRoot
    $payloadProductVersion = Read-InstalledProductVersion -Root $payloadRoot
    if ($payloadProductVersion -ne $productVersion) {
        throw "发布清单与 payload 产品版本不一致。"
    }

    if ($PreflightOnly) {
        $report.status = "pass"
        Write-JsonAtomic -Value $report -Path $reportPath
        Write-InstallProgress -Percent 100 -Stage "预检完成" -Detail "严格 UTF-8、产品版本、文件大小与 SHA-256 校验通过"
        $exitCode = 0
        return
    }

    Write-InstallProgress -Percent 20 -Stage "检查当前版本" -Detail "保存可回滚版本指针和快捷方式状态"
    if ($hadCurrentPointer) {
        $previousCurrent = Read-JsonUtf8 -Path $currentPath
    }
    if ($hadPreviousPointer) {
        $previousPrevious = Read-JsonUtf8 -Path $previousPath
    }
    $preActivationShortcutState = @(
        Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory
    )

    if (-not (Test-Path -LiteralPath $finalPath -PathType Container)) {
        Write-InstallProgress -Percent 35 -Stage "安装预编译文件" -Detail "复制到版本暂存目录"
        if (Test-Path -LiteralPath $stagingPath) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force
        }
        New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
        Copy-Item -Path (Join-Path $payloadRoot "*") -Destination $stagingPath -Recurse -Force
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stagingPath "release-manifest.json") -Force

        Write-InstallProgress -Percent 55 -Stage "校验已安装文件" -Detail "重新计算 SHA-256、文件大小和产品版本"
        Assert-ManifestFiles -Manifest $manifest -Root $stagingPath
        if ((Read-InstalledProductVersion -Root $stagingPath) -ne $productVersion) {
            throw "暂存目录产品版本不一致。"
        }
        Move-Item -LiteralPath $stagingPath -Destination $finalPath
    }
    else {
        Write-InstallProgress -Percent 55 -Stage "复用已验证版本" -Detail "版本目录已存在，重新校验"
        Assert-ManifestFiles -Manifest $manifest -Root $finalPath
        if ((Read-InstalledProductVersion -Root $finalPath) -ne $productVersion) {
            throw "已安装目录产品版本不一致。"
        }
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $finalPath "release-manifest.json") -Force
    }

    $executable = Join-Path $finalPath "Picotoo Pet AI.exe"
    $diagnostic = Join-Path $finalPath "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    $appEntry   = $manifest.files | Where-Object {
        [string]$_.path -eq "Picotoo Pet AI.exe"
    } | Select-Object -First 1
    $diagEntry  = $manifest.files | Where-Object {
        [string]$_.path -eq "tools/diagnostics/PicotooPet.Desktop.Diagnostics.exe"
    } | Select-Object -First 1
    $versionEntry = $manifest.files | Where-Object {
        [string]$_.path -eq "product-version.txt"
    } | Select-Object -First 1
    if ($null -eq $appEntry -or $null -eq $diagEntry -or $null -eq $versionEntry) {
        throw "发布清单缺少主程序、诊断程序或产品版本文件。"
    }

    Write-InstallProgress -Percent 70 -Stage "激活新版本" -Detail "原子更新指针和三处版本快捷方式"
    $activationStarted = $true
    if ($null -ne $previousCurrent) {
        $previousCurrent | Add-Member -NotePropertyName "shortcut_state" `
            -NotePropertyValue @($preActivationShortcutState) -Force
        if (-not ($previousCurrent.PSObject.Properties.Name -contains "product_version")) {
            $previousVersionFile = Join-Path ([string]$previousCurrent.path) "product-version.txt"
            if (Test-Path -LiteralPath $previousVersionFile -PathType Leaf) {
                $previousProductVersion = Read-InstalledProductVersion -Root ([string]$previousCurrent.path)
                $previousCurrent | Add-Member -NotePropertyName "product_version" `
                    -NotePropertyValue $previousProductVersion -Force
            }
        }
        Write-JsonAtomic -Value $previousCurrent -Path $previousPath
    }

    Set-PicotooShortcuts `
        -Executable $executable `
        -ProductVersion $productVersion `
        -DesktopDirectory $DesktopDirectory | Out-Null
    $shortcutValidation = Assert-PicotooShortcuts `
        -Executable $executable `
        -ProductVersion $productVersion `
        -DesktopDirectory $DesktopDirectory `
        -RequireNoLegacy
    $currentPointer = [ordered]@{
        version           = $versionId
        product_version   = $productVersion
        path              = $finalPath
        executable        = $executable
        activated_at      = (Get-Date).ToUniversalTime().ToString("o")
        executable_sha256 = [string]$appEntry.sha256
        diagnostic_sha256 = [string]$diagEntry.sha256
        shortcut_state    = @($shortcutValidation.shortcut_state)
    }
    Write-JsonAtomic -Value $currentPointer -Path $currentPath
    $report.shortcut_paths           = $shortcutValidation.shortcut_paths
    $report.shortcut_state           = @($shortcutValidation.shortcut_state)
    $report.shortcuts_verified       = [bool]$shortcutValidation.shortcuts_verified
    $report.desktop_shortcut         = [string]$shortcutValidation.shortcut_paths.desktop
    $report.desktop_shortcut_created = $true

    Write-InstallProgress -Percent 85 -Stage "启动应用" -Detail "执行新版本激活健康检查"
    $report.activation = Invoke-ActivationCheck `
        -Executable $executable `
        -WorkingDirectory $finalPath `
        -SelfTest:$ActivationSelfTest

    $report.status            = "pass"
    $report.executable_sha256 = [string]$appEntry.sha256
    $report.diagnostic_sha256 = [string]$diagEntry.sha256
    Write-JsonAtomic -Value $report -Path $reportPath
    Write-InstallProgress -Percent 100 -Stage "安装完成" -Detail "预编译版本已激活并验证三处唯一版本快捷方式"
    $exitCode = 0
}
catch {
    $primaryError = $_.Exception.Message
    $restoreError = $null
    if ($activationStarted) {
        try {
            Restore-PreviousActivation
        }
        catch {
            $restoreError = $_.Exception.Message
        }
    }
    if ($null -ne $stagingPath -and (Test-Path -LiteralPath $stagingPath)) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    $report.status = "fail"
    $report.error  = if ($null -eq $restoreError) {
        $primaryError
    }
    else {
        "$primaryError | 自动恢复失败：$restoreError"
    }
    Write-JsonAtomic -Value $report -Path $reportPath
    Write-InstallLog -Level "ERROR" -Message $report.error
    $failedState = [ordered]@{
        schema_version = "2.3.0"
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
    if (-not $PreflightOnly -and
        -not $SuppressReportOpen -and
        (Test-Path -LiteralPath $reportPath)) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
