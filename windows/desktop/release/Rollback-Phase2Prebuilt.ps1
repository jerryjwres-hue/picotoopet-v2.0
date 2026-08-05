# Phase 2 Windows 预编译版本回滚；只切换已验证版本，不删除用户数据。
[CmdletBinding()]
param(
    [string]$DataRoot = "",
    [string]$DesktopDirectory = "",
    [switch]$ActivationSelfTest,
    [switch]$SuppressReportOpen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$commonScript = Join-Path $PSScriptRoot "Phase2Prebuilt.Common.ps1"
if (-not (Test-Path -LiteralPath $commonScript -PathType Leaf)) {
    throw "安装目录缺少 Phase2Prebuilt.Common.ps1。"
}
. $commonScript

if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    $DataRoot = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
}
$DataRoot = [System.IO.Path]::GetFullPath($DataRoot)

$dataRoot       = $DataRoot
$currentPath    = Join-Path $dataRoot "current_version.json"
$previousPath   = Join-Path $dataRoot "previous_version.json"
$reportsRoot    = Join-Path $dataRoot "reports"
$timestamp      = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$reportPath     = Join-Path $reportsRoot "phase2-rollback-$timestamp.json"
$activationPath = Join-Path $reportsRoot "phase2-rollback-activation-$timestamp.json"
$rollbackMutex  = [System.Threading.Mutex]::new($false, "Global\PicotooPetV2.Phase2Installer")
$mutexOwned     = $false
$current        = $null
$previous       = $null
$switched       = $false
$originShortcutState = @()
$targetProductVersion = $null
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

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
    Write-Utf8NoBom -Path $temporary -Value ($Value | ConvertTo-Json -Depth 30)
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-ManifestFiles {
    param([Parameter(Mandatory)]$Manifest, [Parameter(Mandatory)][string]$Root)

    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or
            $relative.Contains("..") -or
            [System.IO.Path]::IsPathRooted($relative)) {
            throw "回滚版本清单包含非法路径：$relative"
        }
        $path = Join-Path $Root ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "回滚版本文件缺失：$relative"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) {
            throw "回滚版本 SHA-256 不一致：$relative"
        }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "回滚版本文件大小不一致：$relative"
        }
    }
}

function Resolve-PointerProductVersion {
    param(
        [Parameter(Mandatory)]$Pointer,
        [Parameter(Mandatory)]$Manifest
    )

    if ($Pointer.PSObject.Properties.Name -contains "product_version" -and
        -not [string]::IsNullOrWhiteSpace([string]$Pointer.product_version)) {
        return Assert-PicotooProductVersion -ProductVersion ([string]$Pointer.product_version)
    }
    if ($Manifest.PSObject.Properties.Name -contains "product_version" -and
        -not [string]::IsNullOrWhiteSpace([string]$Manifest.product_version)) {
        return Assert-PicotooProductVersion -ProductVersion ([string]$Manifest.product_version)
    }
    $versionFile = Join-Path ([string]$Pointer.path) "product-version.txt"
    if (Test-Path -LiteralPath $versionFile -PathType Leaf) {
        $value = [System.IO.File]::ReadAllText(
            $versionFile,
            [System.Text.UTF8Encoding]::new($false, $true)).Trim()
        return Assert-PicotooProductVersion -ProductVersion $value
    }
    return $null
}

function New-LegacyShortcutState {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [string]$DesktopDirectory = ""
    )

    $target = [System.IO.Path]::GetFullPath($Executable)
    $entries = @()
    foreach ($location in @(Get-PicotooManagedShortcutLocations -DesktopDirectory $DesktopDirectory)) {
        $path = Join-Path ([string]$location.directory) "Picotoo Pet AI.lnk"
        $entries += [pscustomobject][ordered]@{
            location          = [string]$location.location
            name              = "Picotoo Pet AI.lnk"
            path              = $path
            target_path       = $target
            arguments         = ""
            working_directory = Split-Path -Parent $target
            icon_location     = "$target,0"
            description       = "Picotoo Pet V2 双机 AI 控制面板"
        }
    }
    return $entries
}

function Assert-ShortcutSnapshotEqual {
    param(
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)]$Actual
    )

    $expectedJson = @($Expected | Sort-Object location, name) | ConvertTo-Json -Depth 20 -Compress
    $actualJson = @($Actual | Sort-Object location, name) | ConvertTo-Json -Depth 20 -Compress
    if ($expectedJson -ne $actualJson) {
        throw "快捷方式快照恢复不精确。expected=$expectedJson actual=$actualJson"
    }
}

function Invoke-RollbackActivationCheck {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [string]$ExpectedProductVersion = "",
        [switch]$SelfTest
    )

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    if ($SelfTest) {
        $arguments = @("--self-test", "--self-test-output", $activationPath)
        $argumentLine = ($arguments | ForEach-Object {
            ConvertTo-NativeArgument -Value $_
        }) -join ' '
        $process = Start-Process -FilePath $Executable -ArgumentList $argumentLine `
            -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "回滚版本自检失败，退出码 $($process.ExitCode)。"
        }
        if (-not (Test-Path -LiteralPath $activationPath -PathType Leaf)) {
            throw "回滚版本自检未生成报告。"
        }
        $selfTestReport = Read-JsonUtf8 -Path $activationPath
        if ([string]$selfTestReport.status -ne "pass") {
            throw "回滚版本自检报告不是 pass。"
        }
        if (-not [string]::IsNullOrWhiteSpace($ExpectedProductVersion) -and
            [string]$selfTestReport.product_version -ne $ExpectedProductVersion) {
            throw "回滚版本产品版本不一致：expected=$ExpectedProductVersion actual=$($selfTestReport.product_version)"
        }
        return [pscustomobject][ordered]@{
            mode       = "self-test"
            status     = "pass"
            report     = $activationPath
            process_id = $process.Id
        }
    }

    $process = Start-Process -FilePath $Executable -WorkingDirectory $WorkingDirectory -PassThru
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) {
        throw "回滚版本启动后立即退出，退出码 $($process.ExitCode)。"
    }
    return [pscustomobject][ordered]@{
        mode       = "interactive"
        status     = "pass"
        report     = $null
        process_id = $process.Id
    }
}

function Restore-RollbackOrigin {
    Write-JsonAtomic -Value $current -Path $currentPath
    Write-JsonAtomic -Value $previous -Path $previousPath
    $restoredState = @(
        Restore-PicotooManagedShortcutSnapshot `
            -ShortcutState $originShortcutState `
            -DesktopDirectory $DesktopDirectory
    )
    Assert-ShortcutSnapshotEqual -Expected $originShortcutState -Actual $restoredState
    $currentProductVersion = ""
    if ($current.PSObject.Properties.Name -contains "product_version") {
        $currentProductVersion = [string]$current.product_version
    }
    $restoredActivation = Invoke-RollbackActivationCheck `
        -Executable ([string]$current.executable) `
        -WorkingDirectory ([string]$current.path) `
        -ExpectedProductVersion $currentProductVersion `
        -SelfTest:$ActivationSelfTest
    return [pscustomobject][ordered]@{
        status       = "pass"
        current      = [string]$current.version
        previous     = [string]$previous.version
        shortcut_state = @($restoredState)
        activation   = $restoredActivation
    }
}

$report = [ordered]@{
    schema_version             = "2.3.0"
    generated_at               = (Get-Date).ToUniversalTime().ToString("o")
    status                     = "running"
    data_root                  = $dataRoot
    restored                   = $null
    restored_product_version   = $null
    replaced                   = $null
    current_before             = $null
    previous_before            = $null
    current_after              = $null
    previous_after             = $null
    restored_executable_sha256 = $null
    shortcut_restore_mode      = $null
    shortcut_paths             = $null
    shortcut_state             = @()
    shortcuts_verified         = $false
    activation                 = $null
    recovery                   = $null
    error                      = $null
}
$exitCode = 1
try {
    try {
        $mutexOwned = $rollbackMutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $mutexOwned = $true
    }
    if (-not $mutexOwned) { throw "安装或回滚正在运行。" }
    if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) {
        throw "当前版本指针不存在。"
    }
    if (-not (Test-Path -LiteralPath $previousPath -PathType Leaf)) {
        throw "没有可回滚的上一版本。"
    }

    $current  = Read-JsonUtf8 -Path $currentPath
    $previous = Read-JsonUtf8 -Path $previousPath
    $originShortcutState = @(
        Get-PicotooManagedShortcutSnapshot -DesktopDirectory $DesktopDirectory
    )
    $report.current_before  = [string]$current.version
    $report.previous_before = [string]$previous.version
    $manifestPath = Join-Path ([string]$previous.path) "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "上一版本缺少发布清单。"
    }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    Assert-ManifestFiles -Manifest $manifest -Root ([string]$previous.path)
    $targetProductVersion = Resolve-PointerProductVersion -Pointer $previous -Manifest $manifest

    $appEntry = $manifest.files | Where-Object {
        [string]$_.path -eq "Picotoo Pet AI.exe"
    } | Select-Object -First 1
    if ($null -eq $appEntry) {
        throw "上一版本清单缺少主程序。"
    }

    $targetShortcutState = @()
    $restoreMode = "pointer-snapshot"
    if ($previous.PSObject.Properties.Name -contains "shortcut_state") {
        $targetShortcutState = @($previous.shortcut_state)
    }
    else {
        $restoreMode = "legacy-pointer-fallback"
        if ($null -ne $targetProductVersion) {
            Set-PicotooShortcuts `
                -Executable ([string]$previous.executable) `
                -ProductVersion $targetProductVersion `
                -DesktopDirectory $DesktopDirectory | Out-Null
            $validation = Assert-PicotooShortcuts `
                -Executable ([string]$previous.executable) `
                -ProductVersion $targetProductVersion `
                -DesktopDirectory $DesktopDirectory `
                -RequireNoLegacy
            $targetShortcutState = @($validation.shortcut_state)
        }
        else {
            $targetShortcutState = @(
                New-LegacyShortcutState `
                    -Executable ([string]$previous.executable) `
                    -DesktopDirectory $DesktopDirectory
            )
        }
    }

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    $switched = $true
    $restoredShortcutState = @(
        Restore-PicotooManagedShortcutSnapshot `
            -ShortcutState $targetShortcutState `
            -DesktopDirectory $DesktopDirectory
    )
    Assert-ShortcutSnapshotEqual -Expected $targetShortcutState -Actual $restoredShortcutState

    $previous | Add-Member -NotePropertyName "shortcut_state" `
        -NotePropertyValue @($restoredShortcutState) -Force
    if ($null -ne $targetProductVersion) {
        $previous | Add-Member -NotePropertyName "product_version" `
            -NotePropertyValue $targetProductVersion -Force
    }
    $current | Add-Member -NotePropertyName "shortcut_state" `
        -NotePropertyValue @($originShortcutState) -Force
    Write-JsonAtomic -Value $previous -Path $currentPath
    Write-JsonAtomic -Value $current -Path $previousPath

    $activation = Invoke-RollbackActivationCheck `
        -Executable ([string]$previous.executable) `
        -WorkingDirectory ([string]$previous.path) `
        -ExpectedProductVersion ([string]$targetProductVersion) `
        -SelfTest:$ActivationSelfTest

    $shortcutPaths = [ordered]@{}
    foreach ($entry in @($restoredShortcutState)) {
        $shortcutPaths[[string]$entry.location] = [string]$entry.path
    }
    $report.status                     = "pass"
    $report.restored                   = [string]$previous.version
    $report.restored_product_version   = $targetProductVersion
    $report.replaced                   = [string]$current.version
    $report.current_after              = [string]$previous.version
    $report.previous_after             = [string]$current.version
    $report.restored_executable_sha256 = [string]$appEntry.sha256
    $report.shortcut_restore_mode      = $restoreMode
    $report.shortcut_paths             = [pscustomobject]$shortcutPaths
    $report.shortcut_state             = @($restoredShortcutState)
    $report.shortcuts_verified         = $true
    $report.activation                 = $activation
    $exitCode                          = 0
}
catch {
    $primaryError = $_.Exception.Message
    if ($switched -and $null -ne $current -and $null -ne $previous) {
        try {
            $report.recovery = Restore-RollbackOrigin
        }
        catch {
            $primaryError = "$primaryError | 恢复回滚前版本失败：$($_.Exception.Message)"
        }
    }
    $report.status = "fail"
    $report.error  = $primaryError
}
finally {
    Write-JsonAtomic -Value $report -Path $reportPath
    if ($mutexOwned) { $rollbackMutex.ReleaseMutex() }
    $rollbackMutex.Dispose()
    if (-not $SuppressReportOpen) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
