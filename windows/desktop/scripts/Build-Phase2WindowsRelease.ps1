# Phase 2 Windows 原生发布构建器；仅在 Windows CI 或受控构建机运行。
[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [string]$Version = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"
$env:DOTNET_CLI_TELEMETRY_OPTOUT = "1"
$env:DOTNET_NOLOGO              = "1"
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

    # Start-Process 会重新拼接参数；包含空格或引号时必须显式加引号。
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Invoke-NativeCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int]$TimeoutSeconds = 900
    )

    # 参数构造                Windows PowerShell 5.1 没有 ProcessStartInfo.ArgumentList。
    $argumentLine = (
        $Arguments |
        ForEach-Object {
            ConvertTo-NativeArgument -Value $_
        }
    ) -join ' '

    # 进程配置                不使用 Start-Process，避免 PassThru ExitCode 为空。
    $startInfo                        = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName               = $FilePath
    $startInfo.Arguments              = $argumentLine
    $startInfo.UseShellExecute        = $false
    $startInfo.CreateNoWindow         = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError  = $true

    $process           = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo

    try {
        # 启动进程                启动失败立即终止，不产生伪退出码。
        if (-not $process.Start()) {
            throw "无法启动原生命令：$FilePath"
        }

        # 异步读取                同时排空 stdout/stderr，避免缓冲区导致死锁。
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        # 超时控制                有限等待；超时后终止并等待进程真正退出。
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                $process.Kill()
            }
            catch {
                Write-Warning (
                    "终止超时进程失败：{0}" -f $_.Exception.Message
                )
            }

            try {
                $process.WaitForExit()
            }
            catch {
                # 超时错误优先        保留原始超时原因。
            }

            throw "原生命令超时（$TimeoutSeconds 秒）：$FilePath"
        }

        # 完成等待                确保重定向输出和进程管理信息均已刷新。
        $process.WaitForExit()
        $process.Refresh()

        $stdout   = $stdoutTask.GetAwaiter().GetResult()
        $stderr   = $stderrTask.GetAwaiter().GetResult()
        $exitCode = [int]$process.ExitCode

        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            Write-Host $stdout.TrimEnd()
        }

        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            Write-Host $stderr.TrimEnd()
        }

        if ($exitCode -ne 0) {
            $tail = (
                ($stderr + "`n" + $stdout) -split "`r?`n" |
                Select-Object -Last 80
            ) -join "`n"

            throw (
                "原生命令失败（退出码 {0}）：{1}`n{2}" -f
                $exitCode,
                $FilePath,
                $tail
            )
        }

        return [pscustomobject]@{
            ExitCode = $exitCode
            StdOut   = $stdout
            StdErr   = $stderr
        }
    }
    finally {
        # 资源释放                CI 长流程中不保留已退出进程句柄。
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Value
    )

    # 发布清单必须跨 PowerShell 5.1、.NET 和 JSON 解析器稳定读取。
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Write-Json {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    Write-Utf8NoBom -Path $Path -Value ($Value | ConvertTo-Json -Depth 20)
}

function Get-FileEntry {
    param(
        [Parameter(Mandatory)][string]$PayloadRoot,
        [Parameter(Mandatory)][string]$Path
    )

    $relative = $Path.Substring($PayloadRoot.Length).TrimStart('\\', '/') -replace '\\', '/'
    return [ordered]@{
        path       = $relative
        sha256     = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = (Get-Item -LiteralPath $Path).Length
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot    = Split-Path -Parent (Split-Path -Parent $desktopRoot)
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $desktopRoot "artifacts\release"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $runNumber = if ([string]::IsNullOrWhiteSpace($env:GITHUB_RUN_NUMBER)) { "local" } else { $env:GITHUB_RUN_NUMBER }
    $commit    = if ([string]::IsNullOrWhiteSpace($env:GITHUB_SHA)) { "nogit" } else { $env:GITHUB_SHA.Substring(0, 12) }
    $Version   = "2.2.0-phase2-slice1-$runNumber-$commit"
}
if ($Version -notmatch '^[A-Za-z0-9._-]+$') {
    throw "版本号只允许字母、数字、点、下划线和连字符。"
}

$dotnet      = (Get-Command "dotnet.exe" -ErrorAction Stop).Source
$sdkVersion  = (Invoke-NativeCommand -FilePath $dotnet -Arguments @("--version")).StdOut.Trim()
if ($sdkVersion -ne "10.0.302") {
    throw "Windows 发布必须使用 .NET SDK 10.0.302，实际为 $sdkVersion。"
}

$solution     = Join-Path $desktopRoot "PicotooPet.Desktop.sln"
$smokeProject = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\PicotooPet.Desktop.Core.SmokeTests.csproj"
$appProject   = Join-Path $desktopRoot "src\PicotooPet.Desktop\PicotooPet.Desktop.csproj"
$diagProject  = Join-Path $desktopRoot "tools\PicotooPet.Desktop.Diagnostics\PicotooPet.Desktop.Diagnostics.csproj"
$workRoot     = Join-Path $OutputRoot "work"
$payloadRoot  = Join-Path $workRoot "payload"
$appOutput    = $payloadRoot
$diagOutput   = Join-Path $payloadRoot "tools\diagnostics"
$packageName  = "PicotooPet-Phase2-Windows-Prebuilt-$Version"
$packageRoot  = Join-Path $workRoot $packageName
$zipPath      = Join-Path $OutputRoot "$packageName.zip"
$shaPath      = "$zipPath.sha256.txt"
$reportPath   = Join-Path $OutputRoot "windows-build-report.json"
$selfTestPath = Join-Path $workRoot "desktop-self-test.json"

if (Test-Path -LiteralPath $OutputRoot) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $appOutput, $diagOutput, $packageRoot -Force | Out-Null

Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "restore", $solution, "--nologo"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "build", $solution, "--configuration", "Release", "--no-restore", "--nologo",
    "-p:ContinuousIntegrationBuild=true"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "run", "--project", $smokeProject, "--configuration", "Release", "--no-build"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "restore", $appProject, "--runtime", "win-x64", "--nologo",
    "-p:PublishReadyToRun=true"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "restore", $diagProject, "--runtime", "win-x64", "--nologo",
    "-p:PublishReadyToRun=true"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "publish", $appProject, "--configuration", "Release", "--runtime", "win-x64",
    "--self-contained", "true", "--output", $appOutput, "--no-restore",
    "-p:PublishSingleFile=true", "-p:PublishReadyToRun=true",
    "-p:PublishReadyToRunShowWarnings=true",
    "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:PublishTrimmed=false",
    "-p:DebugType=None", "-p:DebugSymbols=false", "-p:ContinuousIntegrationBuild=true"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "publish", $diagProject, "--configuration", "Release", "--runtime", "win-x64",
    "--self-contained", "true", "--output", $diagOutput, "--no-restore",
    "-p:PublishSingleFile=true", "-p:PublishReadyToRun=true",
    "-p:PublishReadyToRunShowWarnings=true",
    "-p:IncludeNativeLibrariesForSelfExtract=true", "-p:PublishTrimmed=false",
    "-p:DebugType=None", "-p:DebugSymbols=false", "-p:ContinuousIntegrationBuild=true"
) | Out-Null

$appExecutable  = Join-Path $payloadRoot "Picotoo Pet AI.exe"
$diagExecutable = Join-Path $diagOutput "PicotooPet.Desktop.Diagnostics.exe"
if (-not (Test-Path -LiteralPath $appExecutable))  { throw "发布结果缺少 Picotoo Pet AI.exe。" }
if (-not (Test-Path -LiteralPath $diagExecutable)) { throw "发布结果缺少诊断工具。" }

Invoke-NativeCommand -FilePath $appExecutable -Arguments @(
    "--self-test", "--self-test-output", $selfTestPath
) -TimeoutSeconds 60 | Out-Null
Invoke-NativeCommand -FilePath $diagExecutable -Arguments @("--self-test") -TimeoutSeconds 30 | Out-Null
if (-not (Test-Path -LiteralPath $selfTestPath)) { throw "桌面自检没有生成报告。" }
$selfTest = Get-Content -LiteralPath $selfTestPath -Raw | ConvertFrom-Json
if ([string]$selfTest.status -ne "pass") { throw "桌面自检报告不是 pass。" }

$files = @(
    Get-ChildItem -LiteralPath $payloadRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object { Get-FileEntry -PayloadRoot $payloadRoot -Path $_.FullName }
)
$manifest = [ordered]@{
    schema_version = "2.2.0"
    release_type   = "prebuilt"
    version        = $Version
    target         = "win-x64"
    sdk_version    = $sdkVersion
    built_at       = (Get-Date).ToUniversalTime().ToString("o")
    commit         = if ([string]::IsNullOrWhiteSpace($env:GITHUB_SHA)) { $null } else { $env:GITHUB_SHA }
    signature      = [ordered]@{
        status = "unsigned-ci"
        note   = "Phase 2 内部验收包；正式公开发布前必须加入代码签名。"
    }
    files          = $files
}
$manifestPath = Join-Path $workRoot "release-manifest.json"
Write-Json -Value $manifest -Path $manifestPath

Copy-Item -LiteralPath $payloadRoot -Destination (Join-Path $packageRoot "payload") -Recurse -Force
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $packageRoot "release-manifest.json") -Force
$releaseFiles = @(
    "INSTALL_PHASE2_WINDOWS.vbs",
    "Install-Phase2Prebuilt.ps1",
    "VERIFY_PHASE2_WINDOWS.vbs",
    "Verify-Phase2Prebuilt.ps1",
    "ROLLBACK_PHASE2_WINDOWS.vbs",
    "Rollback-Phase2Prebuilt.ps1",
    "README_INSTALL_CN.txt"
)
foreach ($file in $releaseFiles) {
    Copy-Item -LiteralPath (Join-Path $desktopRoot "release\$file") -Destination $packageRoot -Force
}

Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal
$zipSha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Utf8NoBom -Path $shaPath -Value "$zipSha  $([System.IO.Path]::GetFileName($zipPath))`n"

$report = [ordered]@{
    schema_version = "2.2.0"
    generated_at   = (Get-Date).ToUniversalTime().ToString("o")
    status         = "pass"
    version        = $Version
    sdk_version    = $sdkVersion
    runner         = [Environment]::OSVersion.VersionString
    package        = $zipPath
    package_sha256 = $zipSha
    file_count     = $files.Count
    self_test      = $selfTest
}
Write-Json -Value $report -Path $reportPath
Write-Host "PHASE2_WINDOWS_RELEASE_BUILD=PASS"
Write-Host "PACKAGE=$zipPath"
