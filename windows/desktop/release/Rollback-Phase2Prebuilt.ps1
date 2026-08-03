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
    Write-Utf8NoBom -Path $temporary -Value ($Value | ConvertTo-Json -Depth 20)
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

function Invoke-RollbackActivationCheck {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
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
        $selfTest = Read-JsonUtf8 -Path $activationPath
        if ([string]$selfTest.status -ne "pass") {
            throw "回滚版本自检报告不是 pass。"
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
    Set-PicotooShortcuts `
        -Executable ([string]$current.executable) `
        -DesktopDirectory $DesktopDirectory | Out-Null
    $restoredShortcuts = Assert-PicotooShortcuts `
        -Executable ([string]$current.executable) `
        -DesktopDirectory $DesktopDirectory
    $restoredActivation = Invoke-RollbackActivationCheck `
        -Executable ([string]$current.executable) `
        -WorkingDirectory ([string]$current.path) `
        -SelfTest:$ActivationSelfTest
    return [pscustomobject][ordered]@{
        status     = "pass"
        current    = [string]$current.version
        previous   = [string]$previous.version
        shortcuts  = $restoredShortcuts
        activation = $restoredActivation
    }
}

$report = [ordered]@{
    schema_version             = "2.3.0"
    generated_at               = (Get-Date).ToUniversalTime().ToString("o")
    status                     = "running"
    data_root                  = $dataRoot
    restored                   = $null
    replaced                   = $null
    current_before             = $null
    previous_before            = $null
    current_after              = $null
    previous_after             = $null
    restored_executable_sha256 = $null
    shortcut_paths             = $null
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
    $report.current_before  = [string]$current.version
    $report.previous_before = [string]$previous.version
    $manifestPath = Join-Path ([string]$previous.path) "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "上一版本缺少发布清单。"
    }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    Assert-ManifestFiles -Manifest $manifest -Root ([string]$previous.path)

    $appEntry = $manifest.files | Where-Object {
        [string]$_.path -eq "Picotoo Pet AI.exe"
    } | Select-Object -First 1
    if ($null -eq $appEntry) {
        throw "上一版本清单缺少主程序。"
    }

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    $switched = $true
    Write-JsonAtomic -Value $previous -Path $currentPath
    Write-JsonAtomic -Value $current -Path $previousPath
    Set-PicotooShortcuts `
        -Executable ([string]$previous.executable) `
        -DesktopDirectory $DesktopDirectory | Out-Null
    $shortcutValidation = Assert-PicotooShortcuts `
        -Executable ([string]$previous.executable) `
        -DesktopDirectory $DesktopDirectory
    $activation = Invoke-RollbackActivationCheck `
        -Executable ([string]$previous.executable) `
        -WorkingDirectory ([string]$previous.path) `
        -SelfTest:$ActivationSelfTest

    $report.status                     = "pass"
    $report.restored                   = [string]$previous.version
    $report.replaced                   = [string]$current.version
    $report.current_after              = [string]$previous.version
    $report.previous_after             = [string]$current.version
    $report.restored_executable_sha256 = [string]$appEntry.sha256
    $report.shortcut_paths             = $shortcutValidation.shortcut_paths
    $report.shortcuts_verified         = [bool]$shortcutValidation.shortcuts_verified
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
