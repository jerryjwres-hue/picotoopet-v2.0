# Phase 2 Windows 原生发布构建器；仅在 Windows CI 或受控构建机运行。
[CmdletBinding()]
param(
    [string]$OutputRoot = "",
    [string]$Version = "",
    [string]$VersionLabel = "",
    [string]$ProductVersion = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"
$env:DOTNET_CLI_TELEMETRY_OPTOUT       = "1"
$env:DOTNET_NOLOGO                     = "1"
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = "1"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

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

    $argumentLine = ($Arguments | ForEach-Object {
        ConvertTo-NativeArgument -Value $_
    }) -join ' '

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
        if (-not $process.Start()) {
            throw "无法启动原生命令：$FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            try { $process.WaitForExit() } catch { }
            throw "原生命令超时（$TimeoutSeconds 秒）：$FilePath"
        }
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
            $tail = (($stderr + "`n" + $stdout) -split "`r?`n" |
                Select-Object -Last 80) -join "`n"
            throw "原生命令失败（退出码 $exitCode）：$FilePath`n$tail"
        }

        return [pscustomobject]@{
            ExitCode = $exitCode
            StdOut   = $stdout
            StdErr   = $stderr
        }
    }
    finally {
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

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Value, $encoding)
}

function Write-Json {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    Write-Utf8NoBom -Path $Path -Value ($Value | ConvertTo-Json -Depth 30)
}

function Copy-ReleaseFile {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    if ([System.IO.Path]::GetExtension($Source).Equals(
            ".ps1",
            [System.StringComparison]::OrdinalIgnoreCase)) {
        $strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
        $withBom    = [System.Text.UTF8Encoding]::new($true)
        $text       = [System.IO.File]::ReadAllText($Source, $strictUtf8)
        [System.IO.File]::WriteAllText($Destination, $text, $withBom)
        return
    }

    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Get-FileEntry {
    param(
        [Parameter(Mandatory)][string]$PayloadRoot,
        [Parameter(Mandatory)][string]$Path
    )

    $trimChars = [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $payloadRootFull = [System.IO.Path]::GetFullPath($PayloadRoot).TrimEnd($trimChars)
    $pathFull        = [System.IO.Path]::GetFullPath($Path)
    $payloadPrefix   = $payloadRootFull + [System.IO.Path]::DirectorySeparatorChar
    if (-not $pathFull.StartsWith(
            $payloadPrefix,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "发布文件越过 payload 根目录：$pathFull"
    }

    $relative = $pathFull.Substring($payloadPrefix.Length) -replace '\\', '/'
    return [ordered]@{
        path       = $relative
        sha256     = (Get-FileHash -LiteralPath $pathFull -Algorithm SHA256).Hash.ToLowerInvariant()
        size_bytes = (Get-Item -LiteralPath $pathFull).Length
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot    = Split-Path -Parent (Split-Path -Parent $desktopRoot)
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $desktopRoot "artifacts\release"
}
elseif (-not [System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot $OutputRoot
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

$canonicalProductVersionFile = Join-Path $repoRoot "src\picotoopet_core\product-version.txt"
if (-not (Test-Path -LiteralPath $canonicalProductVersionFile -PathType Leaf)) {
    throw "缺少唯一产品版本源：$canonicalProductVersionFile"
}
$canonicalProductVersion = [System.IO.File]::ReadAllText(
    $canonicalProductVersionFile,
    [System.Text.UTF8Encoding]::new($false, $true)).Trim()
if ($canonicalProductVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "唯一产品版本必须是四段数字：$canonicalProductVersion"
}
if ([string]::IsNullOrWhiteSpace($ProductVersion)) {
    $ProductVersion = $canonicalProductVersion
}
elseif ($ProductVersion -ne $canonicalProductVersion) {
    throw "ProductVersion 必须与唯一版本源一致：expected=$canonicalProductVersion actual=$ProductVersion"
}

if (-not [string]::IsNullOrWhiteSpace($Version) -and
    -not [string]::IsNullOrWhiteSpace($VersionLabel) -and
    $Version -ne $VersionLabel) {
    throw "Version 与 VersionLabel 同时指定时必须一致。"
}
if ([string]::IsNullOrWhiteSpace($Version) -and
    -not [string]::IsNullOrWhiteSpace($VersionLabel)) {
    $Version = $VersionLabel
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $runNumber = if ([string]::IsNullOrWhiteSpace($env:GITHUB_RUN_NUMBER)) {
        "local"
    }
    else {
        $env:GITHUB_RUN_NUMBER
    }
    $sourceHead = if ([string]::IsNullOrWhiteSpace($env:PICOTOO_SOURCE_HEAD_SHA)) {
        if ([string]::IsNullOrWhiteSpace($env:GITHUB_SHA)) { "nogit" } else { $env:GITHUB_SHA }
    }
    else {
        $env:PICOTOO_SOURCE_HEAD_SHA
    }
    $commit = if ($sourceHead -eq "nogit") { "nogit" } else { $sourceHead.Substring(0, 12) }
    $Version = "2.3.0-slice-d-diagnostic-$runNumber-$commit"
}
if ($Version -notmatch '^[A-Za-z0-9._-]+$') {
    throw "版本号只允许字母、数字、点、下划线和连字符。"
}

$dotnet     = (Get-Command "dotnet.exe" -ErrorAction Stop).Source
$sdkVersion = (Invoke-NativeCommand -FilePath $dotnet -Arguments @("--version")).StdOut.Trim()
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
$packageName  = "PicotooPet-Phase2-Windows-Prebuilt-$ProductVersion-$Version"
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
$publishedProductVersionFile = Join-Path $payloadRoot "product-version.txt"
if (-not (Test-Path -LiteralPath $appExecutable -PathType Leaf)) {
    throw "发布结果缺少 Picotoo Pet AI.exe。"
}
if (-not (Test-Path -LiteralPath $diagExecutable -PathType Leaf)) {
    throw "发布结果缺少诊断工具。"
}
if (-not (Test-Path -LiteralPath $publishedProductVersionFile -PathType Leaf)) {
    throw "发布结果缺少 product-version.txt。"
}
$publishedProductVersion = [System.IO.File]::ReadAllText(
    $publishedProductVersionFile,
    [System.Text.UTF8Encoding]::new($false, $true)).Trim()
if ($publishedProductVersion -ne $ProductVersion) {
    throw "发布输出产品版本不一致：expected=$ProductVersion actual=$publishedProductVersion"
}

Invoke-NativeCommand -FilePath $appExecutable -Arguments @(
    "--self-test", "--self-test-output", $selfTestPath
) -TimeoutSeconds 60 | Out-Null
Invoke-NativeCommand -FilePath $diagExecutable -Arguments @("--self-test") -TimeoutSeconds 30 | Out-Null
if (-not (Test-Path -LiteralPath $selfTestPath -PathType Leaf)) {
    throw "桌面自检没有生成报告。"
}
$selfTest = Get-Content -LiteralPath $selfTestPath -Raw | ConvertFrom-Json
if ([string]$selfTest.status -ne "pass") {
    throw "桌面自检报告不是 pass。"
}
if ([string]$selfTest.product_version -ne $ProductVersion -or
    [string]$selfTest.window_title -ne "Picotoo Pet AI $ProductVersion" -or
    [string]$selfTest.control_center_subtitle -ne "Control Center · v$ProductVersion") {
    throw "桌面自检产品版本文案不一致。"
}

$files = @(
    Get-ChildItem -LiteralPath $payloadRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object { Get-FileEntry -PayloadRoot $payloadRoot -Path $_.FullName }
)
$buildCommit = if ([string]::IsNullOrWhiteSpace($env:GITHUB_SHA)) {
    $null
}
else {
    $env:GITHUB_SHA
}
$sourceHead = if ([string]::IsNullOrWhiteSpace($env:PICOTOO_SOURCE_HEAD_SHA)) {
    $buildCommit
}
else {
    $env:PICOTOO_SOURCE_HEAD_SHA
}
$sourceRef = if ([string]::IsNullOrWhiteSpace($env:PICOTOO_SOURCE_REF)) {
    if ([string]::IsNullOrWhiteSpace($env:GITHUB_REF_NAME)) { $null } else { $env:GITHUB_REF_NAME }
}
else {
    $env:PICOTOO_SOURCE_REF
}
$workflowRefAllowed = (
    -not [string]::IsNullOrWhiteSpace($env:GITHUB_WORKFLOW_REF) -and
    (
        $env:GITHUB_WORKFLOW_REF.StartsWith(
            "jerryjwres-hue/picotoopet-v2.0/.github/workflows/windows-control-center-ci.yml@",
            [System.StringComparison]::OrdinalIgnoreCase) -or
        $env:GITHUB_WORKFLOW_REF.StartsWith(
            "jerryjwres-hue/picotoopet-v2.0/.github/workflows/windows-phase2-release.yml@",
            [System.StringComparison]::OrdinalIgnoreCase)
    )
)
$nativeCiVerified = (
    -not [string]::IsNullOrWhiteSpace($env:CI) -and
    $env:CI.Equals("true", [System.StringComparison]::OrdinalIgnoreCase) -and
    -not [string]::IsNullOrWhiteSpace($env:GITHUB_ACTIONS) -and
    $env:GITHUB_ACTIONS.Equals("true", [System.StringComparison]::OrdinalIgnoreCase) -and
    -not [string]::IsNullOrWhiteSpace($env:RUNNER_OS) -and
    $env:RUNNER_OS.Equals("Windows", [System.StringComparison]::OrdinalIgnoreCase) -and
    -not [string]::IsNullOrWhiteSpace($env:GITHUB_REPOSITORY) -and
    $env:GITHUB_REPOSITORY.Equals(
        "jerryjwres-hue/picotoopet-v2.0",
        [System.StringComparison]::OrdinalIgnoreCase) -and
    -not [string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ID) -and
    -not [string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ATTEMPT) -and
    $workflowRefAllowed
)
$manifest = [ordered]@{
    schema_version       = "2.3.0"
    release_type         = "prebuilt"
    version              = $Version
    product_version      = $ProductVersion
    target               = "win-x64"
    sdk_version          = $sdkVersion
    built_at             = (Get-Date).ToUniversalTime().ToString("o")
    commit               = $buildCommit
    build_commit         = $buildCommit
    source_head          = $sourceHead
    source_ref           = $sourceRef
    github_repository    = $env:GITHUB_REPOSITORY
    github_run_id        = $env:GITHUB_RUN_ID
    github_run_attempt   = $env:GITHUB_RUN_ATTEMPT
    github_workflow_ref  = $env:GITHUB_WORKFLOW_REF
    native_ci_verified   = $nativeCiVerified
    user_install_allowed = $nativeCiVerified
    signature            = [ordered]@{
        status = "unsigned-ci"
        note   = "原生 Windows CI 内部验收包；公开发布前仍需代码签名。"
    }
    files                = $files
}
$manifestPath = Join-Path $workRoot "release-manifest.json"
Write-Json -Value $manifest -Path $manifestPath

Copy-Item -LiteralPath $payloadRoot -Destination (Join-Path $packageRoot "payload") -Recurse -Force
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $packageRoot "release-manifest.json") -Force
$releaseFiles = @(
    "Phase2Prebuilt.Common.ps1",
    "INSTALL_PHASE2_WINDOWS.vbs",
    "Install-Phase2Prebuilt.ps1",
    "VERIFY_PHASE2_WINDOWS.vbs",
    "Verify-Phase2Prebuilt.ps1",
    "ROLLBACK_PHASE2_WINDOWS.vbs",
    "Rollback-Phase2Prebuilt.ps1",
    "README_INSTALL_CN.txt"
)
foreach ($file in $releaseFiles) {
    Copy-ReleaseFile `
        -Source (Join-Path $desktopRoot "release\$file") `
        -Destination (Join-Path $packageRoot $file)
}

Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipSha = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Utf8NoBom -Path $shaPath -Value "$zipSha  $([System.IO.Path]::GetFileName($zipPath))`n"

$report = [ordered]@{
    schema_version       = "2.3.0"
    generated_at         = (Get-Date).ToUniversalTime().ToString("o")
    status               = "pass"
    version              = $Version
    product_version      = $ProductVersion
    sdk_version          = $sdkVersion
    runner               = [Environment]::OSVersion.VersionString
    target               = "win-x64"
    package              = $zipPath
    package_sha256       = $zipSha
    file_count           = $files.Count
    native_ci_verified   = $nativeCiVerified
    user_install_allowed = $nativeCiVerified
    source_head          = $sourceHead
    source_ref           = $sourceRef
    build_commit         = $buildCommit
    github_repository    = $env:GITHUB_REPOSITORY
    github_run_id        = $env:GITHUB_RUN_ID
    github_run_attempt   = $env:GITHUB_RUN_ATTEMPT
    github_workflow_ref  = $env:GITHUB_WORKFLOW_REF
    self_test            = $selfTest
}
Write-Json -Value $report -Path $reportPath
Write-Host "PHASE2_WINDOWS_RELEASE_BUILD=PASS"
Write-Host "PRODUCT_VERSION=$ProductVersion"
Write-Host "PACKAGE=$zipPath"
Write-Host "SHA256=$zipSha"
