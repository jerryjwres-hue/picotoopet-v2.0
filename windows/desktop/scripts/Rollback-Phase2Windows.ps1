# Phase 2 Windows Desktop 版本回滚；只切换程序指针和快捷方式，不删除用户数据。
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

function Write-JsonAtomic {
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Path)
    # 同卷临时文件替换，保证版本指针永远是完整 JSON。
    $temporary = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Set-PicotooShortcuts {
    param([Parameter(Mandatory)][string]$Executable)
    # 启动菜单与开机入口必须同时指向同一已校验版本。
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
    schema_version    = "2.2.0"
    generated_at      = (Get-Date).ToUniversalTime().ToString("o")
    status            = "running"
    restored          = $null
    replaced          = $null
    executable_sha256 = $null
    diagnostic_sha256 = $null
    error             = $null
}

try {
    try {
        $mutexOwned = $rollbackMutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        # 接管异常退出进程遗留的互斥锁，并从完整指针重新验证。
        $mutexOwned = $true
    }
    if (-not $mutexOwned) { throw "安装或回滚正在运行，请稍后重试。" }
    if (-not (Test-Path -LiteralPath $currentPath)) { throw "当前版本指针不存在。" }
    if (-not (Test-Path -LiteralPath $previousPath)) { throw "没有可回滚的上一版本。" }

    $current  = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    $previous = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
    $manifestPath = Join-Path $previous.path "version.json"
    $diagnostic   = Join-Path $previous.path "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    if (-not (Test-Path -LiteralPath $previous.executable)) { throw "上一版本主程序不存在。" }
    if (-not (Test-Path -LiteralPath $diagnostic)) { throw "上一版本诊断程序不存在。" }
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "上一版本清单不存在。" }

    $manifest       = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $executableHash = (Get-FileHash -LiteralPath $previous.executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $diagnosticHash = (Get-FileHash -LiteralPath $diagnostic -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($executableHash -ne [string]$manifest.executable_sha256) {
        throw "上一版本主程序 SHA-256 校验失败。"
    }
    if ($diagnosticHash -ne [string]$manifest.diagnostic_sha256) {
        throw "上一版本诊断程序 SHA-256 校验失败。"
    }

    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    # 在第一次指针写入前标记切换，使任一原子写失败都触发完整恢复。
    $switched = $true
    Write-JsonAtomic -Value $previous -Path $currentPath
    Write-JsonAtomic -Value $current -Path $previousPath
    Set-PicotooShortcuts -Executable $previous.executable
    Start-Process -FilePath $previous.executable -WorkingDirectory $previous.path

    $report.status            = "pass"
    $report.restored          = $previous.version
    $report.replaced          = $current.version
    $report.executable_sha256 = $executableHash
    $report.diagnostic_sha256 = $diagnosticHash
}
catch {
    $primaryError = $_.Exception.Message
    $restoreError = $null
    if ($switched -and $null -ne $current -and $null -ne $previous) {
        try {
            # 回滚版本启动失败时恢复回滚前状态，避免两个指针都指向错误版本。
            Write-JsonAtomic -Value $current -Path $currentPath
            Write-JsonAtomic -Value $previous -Path $previousPath
            Set-PicotooShortcuts -Executable ([string]$current.executable)
            Start-Process -FilePath $current.executable -WorkingDirectory $current.path
        }
        catch {
            $restoreError = $_.Exception.Message
        }
    }
    $report.status = "fail"
    $report.error  = if ($null -eq $restoreError) {
        $primaryError
    }
    else {
        "$primaryError | 恢复回滚前版本失败：$restoreError"
    }
}
finally {
    Write-JsonAtomic -Value $report -Path $reportPath
    if ($mutexOwned) { $rollbackMutex.ReleaseMutex() }
    $rollbackMutex.Dispose()
    Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
}

if ($report.status -ne "pass") { exit 1 }
