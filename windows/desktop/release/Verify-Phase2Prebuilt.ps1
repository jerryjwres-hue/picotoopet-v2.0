# Phase 2 Windows 预编译安装验证；校验文件、快捷方式、进程和真实双机链路。
[CmdletBinding()]
param(
    [int]$RestSamples = 500,
    [int]$TaskSamples = 500,
    [int]$SocketSamples = 500,
    [string]$DataRoot = "",
    [string]$DesktopDirectory = "",
    [switch]$OfflinePackageOnly,
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
            throw "当前版本清单包含非法路径：$relative"
        }
        $path = Join-Path $Root ($relative -replace '/', [System.IO.Path]::DirectorySeparatorChar)
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "当前版本文件缺失：$relative"
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) {
            throw "当前版本 SHA-256 不一致：$relative"
        }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "当前版本文件大小不一致：$relative"
        }
    }
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int]$TimeoutSeconds = 120
    )

    $argumentLine = ($Arguments | ForEach-Object {
        ConvertTo-NativeArgument -Value $_
    }) -join ' '
    $process = Start-Process -FilePath $FilePath -ArgumentList $argumentLine `
        -WorkingDirectory (Split-Path -Parent $FilePath) `
        -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        throw "验证进程超时：$FilePath"
    }
    if ($process.ExitCode -ne 0) {
        throw "验证进程失败（退出码 $($process.ExitCode)）：$FilePath"
    }
    return [pscustomobject][ordered]@{
        executable = $FilePath
        exit_code  = [int]$process.ExitCode
        process_id = $process.Id
    }
}

$dataRoot     = $DataRoot
$currentPath  = Join-Path $dataRoot "current_version.json"
$reportsRoot  = Join-Path $dataRoot "reports"
$reportPath   = Join-Path $reportsRoot "phase2-windows-verification.json"
$selfTestPath = Join-Path $reportsRoot "phase2-windows-verification-self-test.json"
$settingsPath = Join-Path $env:LOCALAPPDATA "PicotooPetV2\Desktop\settings.json"
$baseUrl      = "http://127.0.0.1:8766"
$exitCode     = 2
New-Item -ItemType Directory -Path $reportsRoot -Force | Out-Null

try {
    if (-not (Test-Path -LiteralPath $currentPath -PathType Leaf)) {
        throw "尚未安装 Phase 2 Windows Desktop。"
    }
    $current      = Read-JsonUtf8 -Path $currentPath
    $manifestPath = Join-Path ([string]$current.path) "release-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "当前版本缺少 release-manifest.json。"
    }
    $manifest = Read-JsonUtf8 -Path $manifestPath
    Assert-ManifestFiles -Manifest $manifest -Root ([string]$current.path)

    $executable = [string]$current.executable
    $diagnostic = Join-Path ([string]$current.path) "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    $shortcutValidation = Assert-PicotooShortcuts `
        -Executable $executable `
        -DesktopDirectory $DesktopDirectory
    $releaseValidation = [ordered]@{
        version             = [string]$current.version
        data_root           = $dataRoot
        manifest            = $manifestPath
        manifest_file_count = @($manifest.files).Count
        shortcuts_verified  = [bool]$shortcutValidation.shortcuts_verified
        shortcut_paths      = $shortcutValidation.shortcut_paths
        executable_sha256   = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        diagnostic_sha256   = (Get-FileHash -LiteralPath $diagnostic -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    if ($OfflinePackageOnly) {
        $appCheck = Invoke-CheckedProcess -FilePath $executable -Arguments @(
            "--self-test", "--self-test-output", $selfTestPath
        )
        if (-not (Test-Path -LiteralPath $selfTestPath -PathType Leaf)) {
            throw "桌面自检未生成报告。"
        }
        $selfTest = Read-JsonUtf8 -Path $selfTestPath
        if ([string]$selfTest.status -ne "pass") {
            throw "桌面自检报告不是 pass。"
        }
        $diagnosticCheck = Invoke-CheckedProcess -FilePath $diagnostic -Arguments @("--self-test")
        $offlineReport = [ordered]@{
            schema_version     = "2.3.0"
            generated_at       = (Get-Date).ToUniversalTime().ToString("o")
            status             = "pass"
            mode               = "offline-package"
            release_validation = $releaseValidation
            app_self_test      = $selfTest
            app_process        = $appCheck
            diagnostic_process = $diagnosticCheck
            errors             = @()
        }
        Write-JsonAtomic -Value $offlineReport -Path $reportPath
        $exitCode = 0
    }
    else {
        if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
            $settings = Read-JsonUtf8 -Path $settingsPath
            if (-not [string]::IsNullOrWhiteSpace([string]$settings.macBaseUrl)) {
                $candidate = [Uri]$settings.macBaseUrl
                if ($candidate.IsAbsoluteUri) {
                    $baseUrl = $candidate.AbsoluteUri.TrimEnd('/')
                }
            }
        }

        if ($null -eq (Get-Process -Name "Picotoo Pet AI" -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $executable -WorkingDirectory ([string]$current.path)
            Start-Sleep -Seconds 2
        }

        $arguments = @(
            "--base-url", $baseUrl,
            "--output", $reportPath,
            "--rest-samples", [string]$RestSamples,
            "--task-samples", [string]$TaskSamples,
            "--socket-samples", [string]$SocketSamples
        )
        $argumentLine = ($arguments | ForEach-Object {
            ConvertTo-NativeArgument -Value $_
        }) -join ' '
        $process = Start-Process -FilePath $diagnostic -ArgumentList $argumentLine `
            -WorkingDirectory (Split-Path -Parent $diagnostic) `
            -WindowStyle Hidden -Wait -PassThru
        $exitCode = [int]$process.ExitCode
        if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
            throw "诊断程序未生成报告。"
        }
        $diagnosticReport = Read-JsonUtf8 -Path $reportPath
        $diagnosticReport | Add-Member -NotePropertyName "release_validation" `
            -NotePropertyValue $releaseValidation -Force
        Write-JsonAtomic -Value $diagnosticReport -Path $reportPath
    }
}
catch {
    $fallback = [ordered]@{
        schema_version = "2.3.0"
        generated_at   = (Get-Date).ToUniversalTime().ToString("o")
        status         = "fail"
        mode           = if ($OfflinePackageOnly) { "offline-package" } else { "connected" }
        environment    = [ordered]@{
            base_url  = $baseUrl
            data_root = $dataRoot
        }
        release_validation = $null
        metrics        = [ordered]@{}
        errors         = @("VERIFIER_FAILURE | $($_.Exception.GetType().Name): $($_.Exception.Message)")
    }
    Write-JsonAtomic -Value $fallback -Path $reportPath
    $exitCode = 2
}
finally {
    if (-not $SuppressReportOpen -and (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        Start-Process -FilePath "notepad.exe" -ArgumentList @($reportPath)
    }
}

exit $exitCode
