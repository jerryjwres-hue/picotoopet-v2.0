# Phase 2 Windows 预编译版本回滚；只切换已验证版本，不删除用户数据。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$dataRoot      = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$currentPath   = Join-Path $dataRoot "current_version.json"
$previousPath  = Join-Path $dataRoot "previous_version.json"
$reportsRoot   = Join-Path $dataRoot "reports"
$timestamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$reportPath    = Join-Path $reportsRoot "phase2-rollback-$timestamp.json"
$rollbackMutex = [System.Threading.Mutex]::new($false, "Global\PicotooPetV2.Phase2Installer")
$mutexOwned    = $false
$current       = $null
$previous      = $null
$switched      = $false
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

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
        if (-not (Test-Path -LiteralPath $path)) { throw "回滚版本文件缺失：$relative" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) { throw "回滚版本 SHA-256 不一致：$relative" }
    }
}

function Set-PicotooShortcuts {
    param([Parameter(Mandatory)][string]$Executable)

    $shell = New-Object -ComObject WScript.Shell
    $paths = @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Picotoo Pet AI.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Picotoo Pet AI.lnk")
    )
    foreach ($shortcutPath in $paths) {
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath       = $Executable
        $shortcut.WorkingDirectory = Split-Path -Parent $Executable
        $shortcut.Description      = "Picotoo Pet V2 双机 AI 控制面板"
        $shortcut.Save()
    }
}

$report = [ordered]@{
    schema_version = "2.2.0"
    generated_at   = (Get-Date).ToUniversalTime().ToString("o")
    status         = "running"
    restored       = $null
    replaced       = $null
    error          = $null
}
$exitCode = 1
try {
    try { $mutexOwned = $rollbackMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $mutexOwned = $true }
    if (-not $mutexOwned) { throw "安装或回滚正在运行。" }
    if (-not (Test-Path -LiteralPath $currentPath))  { throw "当前版本指针不存在。" }
    if (-not (Test-Path -LiteralPath $previousPath)) { throw "没有可回滚的上一版本。" }

    $current      = Read-JsonUtf8 -Path $currentPath
    $previous     = Read-JsonUtf8 -Path $previousPath
    $manifestPath = Join-Path $previous.path "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "上一版本缺少发布清单。" }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    Assert-ManifestFiles -Manifest $manifest -Root $previous.path

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    $switched = $true
    Write-JsonAtomic -Value $previous -Path $currentPath
    Write-JsonAtomic -Value $current -Path $previousPath
    Set-PicotooShortcuts -Executable ([string]$previous.executable)
    $process = Start-Process -FilePath $previous.executable -WorkingDirectory $previous.path -PassThru
    Start-Sleep -Seconds 2
    $process.Refresh()
    if ($process.HasExited) { throw "回滚版本启动后立即退出。" }

    $report.status   = "pass"
    $report.restored = $previous.version
    $report.replaced = $current.version
    $exitCode        = 0
}
catch {
    $primaryError = $_.Exception.Message
    if ($switched -and $null -ne $current -and $null -ne $previous) {
        try {
            Write-JsonAtomic -Value $current -Path $currentPath
            Write-JsonAtomic -Value $previous -Path $previousPath
            Set-PicotooShortcuts -Executable ([string]$current.executable)
            Start-Process -FilePath $current.executable -WorkingDirectory $current.path
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
    Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
}

exit $exitCode
