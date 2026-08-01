# Phase 2 Windows Desktop 开发构建入口；所有步骤失败时返回非零退出码。
[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [switch]$InstallSdk
)

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
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $desktopRoot "artifacts"
}

function Get-DotNet10 {
    # 优先使用当前 PATH，随后检查微软默认安装目录。
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

function Install-DotNet10Sdk {
    # 仅使用 Microsoft Learn 公布的官方 WinGet 包标识。
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "未检测到 WinGet，无法自动安装 Microsoft.DotNet.SDK.10。"
    }
    Invoke-NativeCommand -FilePath $winget.Source -Arguments @(
        "install", "--id", "Microsoft.DotNet.SDK.10", "--exact", "--source", "winget",
        "--accept-package-agreements", "--accept-source-agreements", "--silent",
        "--disable-interactivity"
    ) | Out-Null
}

$dotnet = Get-DotNet10
if ($null -eq $dotnet -and $InstallSdk) {
    Install-DotNet10Sdk
    $dotnet = Get-DotNet10
}
if ($null -eq $dotnet) {
    throw "需要 .NET 10 SDK。请使用安装入口自动安装，或运行 winget install Microsoft.DotNet.SDK.10。"
}

$smokeProject = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\PicotooPet.Desktop.Core.SmokeTests.csproj"
$appProject   = Join-Path $desktopRoot "src\PicotooPet.Desktop\PicotooPet.Desktop.csproj"
$diagProject  = Join-Path $desktopRoot "tools\PicotooPet.Desktop.Diagnostics\PicotooPet.Desktop.Diagnostics.csproj"
$appOutput    = Join-Path $OutputRoot "app"
$diagOutput   = Join-Path $OutputRoot "tools\diagnostics"

if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
New-Item -ItemType Directory -Path $appOutput, $diagOutput -Force | Out-Null

Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "run", "--project", $smokeProject, "--configuration", "Release"
) | Out-Null
Invoke-NativeCommand -FilePath $dotnet -Arguments @(
    "publish", $appProject, "--configuration", "Release", "--runtime", "win-x64",
    "--self-contained", "true", "--output", $appOutput,
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

Write-Host "PHASE2_WINDOWS_BUILD=PASS"
Write-Host "OUTPUT=$OutputRoot"
