# Phase 2 Windows Desktop 一键构建与版本化安装；不读取或修改 Protected 数据。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)
    # Start-Process 会把数组重新拼接；含空格参数必须显式加引号。
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Invoke-NativeCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )
    # Windows PowerShell 5.1 会把正常 stderr 包装成 NativeCommandError；改用真实退出码。
    $token      = [Guid]::NewGuid().ToString('N')
    $stdoutPath = Join-Path $env:TEMP "picotoo-native-$token.stdout.log"
    $stderrPath = Join-Path $env:TEMP "picotoo-native-$token.stderr.log"
    $argumentLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join ' '
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $argumentLine `
            -Wait -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $stdout = if (Test-Path -LiteralPath $stdoutPath) {
            Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
        } else { '' }
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        } else { '' }
        if (-not [string]::IsNullOrWhiteSpace($stdout)) { Write-Host $stdout.TrimEnd() }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) { Write-Host $stderr.TrimEnd() }
        if ($process.ExitCode -ne 0 -and -not $AllowFailure) {
            $tail = (($stderr + "`n" + $stdout) -split "`r?`n" | Select-Object -Last 30) -join "`n"
            throw "原生命令失败（退出码 $($process.ExitCode)）：$FilePath`n$tail"
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut   = $stdout
            StdErr   = $stderr
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}


$desktopRoot = Split-Path -Parent $PSScriptRoot
$dataRoot    = Join-Path $env:LOCALAPPDATA "PicotooPetV2\DesktopApp"
$versionsRoot = Join-Path $dataRoot "versions"
$reportsRoot  = Join-Path $dataRoot "reports"
$logsRoot     = Join-Path $dataRoot "logs"
$currentPath  = Join-Path $dataRoot "current_version.json"
$previousPath = Join-Path $dataRoot "previous_version.json"
$timestamp    = Get-Date -Format "yyyyMMdd-HHmmss"
$versionId    = "2.2.0-phase2-$timestamp-$PID"
$stagingPath  = Join-Path $versionsRoot ".staging-$versionId"
$finalPath    = Join-Path $versionsRoot $versionId
$reportPath   = Join-Path $reportsRoot "phase2-install-$timestamp.json"
$logPath      = Join-Path $logsRoot "phase2-install-$timestamp-$PID.log"
$installMutex = [System.Threading.Mutex]::new($false, "Global\PicotooPetV2.Phase2Installer")
$mutexOwned       = $false
$previousCurrent   = $null
$previousPrevious  = $null
$activationStarted = $false
$hadCurrentPointer = Test-Path -LiteralPath $currentPath
$hadPreviousPointer = Test-Path -LiteralPath $previousPath

New-Item -ItemType Directory -Path $versionsRoot, $reportsRoot, $logsRoot -Force | Out-Null
Start-Transcript -Path $logPath -Force | Out-Null

function Write-JsonAtomic {
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Path)
    # 同卷临时文件替换，避免断电后留下半个版本指针。
    $temporary = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-DotNet10 {
    # 检测可用 .NET 10 SDK，并允许同一大版本内较新的安全补丁和 Feature Band。
    $candidates = @()
    $command = Get-Command "dotnet.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) { $candidates += $command.Source }
    $candidates += (Join-Path $env:ProgramFiles "dotnet\dotnet.exe")
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $result = Invoke-NativeCommand -FilePath $candidate -Arguments @("--list-sdks") -AllowFailure
        if ($result.ExitCode -eq 0 -and ($result.StdOut -match '(?m)^10\.')) { return $candidate }
    }
    return $null
}

function Ensure-DotNet10Sdk {
    $dotnet = Get-DotNet10
    if ($null -ne $dotnet) { return $dotnet }
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "缺少 WinGet，无法自动安装官方 Microsoft.DotNet.SDK.10。"
    }
    Invoke-NativeCommand -FilePath $winget.Source -Arguments @(
        "install", "--id", "Microsoft.DotNet.SDK.10", "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent",
        "--disable-interactivity"
    ) | Out-Null
    $dotnet = Get-DotNet10
    if ($null -eq $dotnet) { throw ".NET 10 SDK 安装后仍未被检测到。" }
    return $dotnet
}

function Get-PicotooShortcutPaths {
    # 所有快捷方式路径集中定义，安装与恢复使用完全相同的集合。
    return @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Picotoo Pet AI.lnk"),
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Picotoo Pet AI.lnk")
    )
}

function Set-PicotooShortcuts {
    param([Parameter(Mandatory)][string]$Executable)
    # 快捷方式始终指向经过哈希登记的当前版本，不使用可被劫持的搜索路径。
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
    # 首次安装激活失败时移除本次创建的入口，避免用户打开不存在的版本。
    foreach ($shortcutPath in Get-PicotooShortcutPaths) {
        Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    }
}

function Restore-PreviousActivation {
    # 指针、快捷方式和上一版本指针必须作为一个逻辑事务恢复。
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
    schema_version = "2.2.0"
    generated_at   = (Get-Date).ToUniversalTime().ToString("o")
    status         = "running"
    version        = $versionId
    install_path   = $finalPath
    log            = $logPath
    executable_sha256 = $null
    diagnostic_sha256 = $null
    error             = $null
}

try {
    try {
        $mutexOwned = $installMutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        # 上一次安装进程异常退出时接管遗留锁，随后执行完整一致性安装。
        $mutexOwned = $true
    }
    if (-not $mutexOwned) {
        throw "已有 Phase 2 安装正在运行，请等待当前安装报告完成。"
    }

    $dotnet = Ensure-DotNet10Sdk
    if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Recurse -Force }
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null

    $smokeProject = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\PicotooPet.Desktop.Core.SmokeTests.csproj"
    $appProject   = Join-Path $desktopRoot "src\PicotooPet.Desktop\PicotooPet.Desktop.csproj"
    $diagProject  = Join-Path $desktopRoot "tools\PicotooPet.Desktop.Diagnostics\PicotooPet.Desktop.Diagnostics.csproj"
    $diagOutput   = Join-Path $stagingPath "tools\diagnostics"
    New-Item -ItemType Directory -Path $diagOutput -Force | Out-Null

    Invoke-NativeCommand -FilePath $dotnet -Arguments @(
        "run", "--project", $smokeProject, "--configuration", "Release"
    ) | Out-Null
    Invoke-NativeCommand -FilePath $dotnet -Arguments @(
        "publish", $appProject, "--configuration", "Release", "--runtime", "win-x64",
        "--self-contained", "true", "--output", $stagingPath,
        "-p:PublishSingleFile=true", "-p:PublishReadyToRun=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:PublishTrimmed=false",
        "-p:DebugType=None", "-p:DebugSymbols=false"
    ) | Out-Null
    Invoke-NativeCommand -FilePath $dotnet -Arguments @(
        "publish", $diagProject, "--configuration", "Release", "--runtime", "win-x64",
        "--self-contained", "true", "--output", $diagOutput,
        "-p:PublishSingleFile=true", "-p:PublishReadyToRun=true",
        "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:PublishTrimmed=false",
        "-p:DebugType=None", "-p:DebugSymbols=false"
    ) | Out-Null

    $executable = Join-Path $stagingPath "Picotoo Pet AI.exe"
    $diagnostic = Join-Path $diagOutput "PicotooPet.Desktop.Diagnostics.exe"
    if (-not (Test-Path -LiteralPath $executable)) { throw "发布结果缺少 Picotoo Pet AI.exe。" }
    if (-not (Test-Path -LiteralPath $diagnostic)) { throw "发布结果缺少诊断工具。" }

    $manifest = [ordered]@{
        schema_version  = "2.2.0"
        version         = $versionId
        built_at        = (Get-Date).ToUniversalTime().ToString("o")
        executable      = "Picotoo Pet AI.exe"
        executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        diagnostic_sha256 = (Get-FileHash -LiteralPath $diagnostic -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    Write-JsonAtomic -Value $manifest -Path (Join-Path $stagingPath "version.json")
    Move-Item -LiteralPath $stagingPath -Destination $finalPath

    if ($hadCurrentPointer) {
        $previousCurrent = Get-Content -LiteralPath $currentPath -Raw | ConvertFrom-Json
    }
    if ($hadPreviousPointer) {
        $previousPrevious = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
    }
    $activationStarted = $true
    if ($null -ne $previousCurrent) {
        Write-JsonAtomic -Value $previousCurrent -Path $previousPath
    }
    $currentPointer = [ordered]@{
        version        = $versionId
        path           = $finalPath
        executable     = (Join-Path $finalPath "Picotoo Pet AI.exe")
        activated_at   = (Get-Date).ToUniversalTime().ToString("o")
        executable_sha256 = $manifest.executable_sha256
    }
    Write-JsonAtomic -Value $currentPointer -Path $currentPath
    Set-PicotooShortcuts -Executable $currentPointer.executable

    # 升级切换前关闭旧桌面，避免两个版本同时消费同一事件流和状态仓库。
    Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Process -FilePath $currentPointer.executable -WorkingDirectory $finalPath
    $report.status = "pass"
    $report.executable_sha256 = $manifest.executable_sha256
    $report.diagnostic_sha256 = $manifest.diagnostic_sha256
    Write-JsonAtomic -Value $report -Path $reportPath
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
    $report.status = "fail"
    $report.error  = if ($null -eq $restoreError) {
        $primaryError
    }
    else {
        "$primaryError | 自动恢复失败：$restoreError"
    }
    if (Test-Path -LiteralPath $stagingPath) { Remove-Item -LiteralPath $stagingPath -Recurse -Force }
    Write-JsonAtomic -Value $report -Path $reportPath
}
finally {
    if ($mutexOwned) { $installMutex.ReleaseMutex() }
    $installMutex.Dispose()
    Stop-Transcript | Out-Null
    Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
}

if ($report.status -ne "pass") { exit 1 }
