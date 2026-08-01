# Phase 2 Windows 预编译发布包门禁；必须在原生 Windows runner 上通过。
[CmdletBinding()]
param(
    [string]$ReleaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory)][string]$Value)

    # Start-Process 会重新拼接参数；包含空格或引号时必须显式加引号。
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '"', '\\"') + '"'
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int]$TimeoutSeconds = 60
    )

    # 发布门禁必须验证真实退出码，并强制终止超时进程。
    $argumentLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ }) -join ' '
    $process      = Start-Process -FilePath $FilePath -ArgumentList $argumentLine -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        throw "进程自检超时：$FilePath"
    }
    if ($process.ExitCode -ne 0) {
        throw "进程自检失败（退出码 $($process.ExitCode)）：$FilePath"
    }
    return $process.ExitCode
}

function Assert-ManifestFiles {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$PayloadRoot
    )

    foreach ($entry in $Manifest.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or $relative.Contains("..")) {
            throw "发布清单包含非法相对路径：$relative"
        }
        $path = Join-Path $PayloadRoot ($relative -replace '/', '\\')
        if (-not (Test-Path -LiteralPath $path)) { throw "发布文件缺失：$relative" }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne [string]$entry.sha256) { throw "发布文件哈希不一致：$relative" }
        if ((Get-Item -LiteralPath $path).Length -ne [long]$entry.size_bytes) {
            throw "发布文件大小不一致：$relative"
        }
    }
}

function Assert-PowerShellSyntax {
    param([Parameter(Mandatory)][string]$Path)

    # Windows PowerShell 5.1 自带解析器直接验证用户将执行的脚本语法。
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) {
        $messages = ($errors | ForEach-Object { $_.Message }) -join ' | '
        throw "PowerShell 语法失败：$Path | $messages"
    }
}

$desktopRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
    $ReleaseRoot = Join-Path $desktopRoot "artifacts\release"
}
$zip = Get-ChildItem -LiteralPath $ReleaseRoot -Filter "PicotooPet-Phase2-Windows-Prebuilt-*.zip" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $zip) { throw "未找到 Phase 2 Windows 预编译 ZIP。" }

$tempRoot = Join-Path $env:TEMP "picotoo-release-test-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    Expand-Archive -LiteralPath $zip.FullName -DestinationPath $tempRoot -Force
    $manifestPath = Join-Path $tempRoot "release-manifest.json"
    $payloadRoot  = Join-Path $tempRoot "payload"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "ZIP 缺少 release-manifest.json。" }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.release_type -ne "prebuilt") { throw "发布类型不是 prebuilt。" }
    if ([string]$manifest.target -ne "win-x64")       { throw "发布目标不是 win-x64。" }
    Assert-ManifestFiles -Manifest $manifest -PayloadRoot $payloadRoot

    $installer = Join-Path $tempRoot "Install-Phase2Prebuilt.ps1"
    $verifier  = Join-Path $tempRoot "Verify-Phase2Prebuilt.ps1"
    $rollback  = Join-Path $tempRoot "Rollback-Phase2Prebuilt.ps1"
    Assert-PowerShellSyntax -Path $installer
    Assert-PowerShellSyntax -Path $verifier
    Assert-PowerShellSyntax -Path $rollback

    $vbsBytes = [System.IO.File]::ReadAllBytes((Join-Path $tempRoot "INSTALL_PHASE2_WINDOWS.vbs"))
    if ($vbsBytes.Length -ge 3 -and $vbsBytes[0] -eq 0xEF -and $vbsBytes[1] -eq 0xBB -and $vbsBytes[2] -eq 0xBF) {
        throw "安装 VBS 含 UTF-8 BOM。"
    }

    $appExecutable  = Join-Path $payloadRoot "Picotoo Pet AI.exe"
    $diagExecutable = Join-Path $payloadRoot "tools\diagnostics\PicotooPet.Desktop.Diagnostics.exe"
    $selfTestPath   = Join-Path $tempRoot "desktop-self-test.json"
    [void](Invoke-CheckedProcess -FilePath $appExecutable -Arguments @(
        "--self-test", "--self-test-output", $selfTestPath
    ))
    [void](Invoke-CheckedProcess -FilePath $diagExecutable -Arguments @("--self-test"))
    if (-not (Test-Path -LiteralPath $selfTestPath)) { throw "桌面自检报告缺失。" }
    $selfTest = Get-Content -LiteralPath $selfTestPath -Raw | ConvertFrom-Json
    if ([string]$selfTest.status -ne "pass") { throw "桌面自检报告不是 pass。" }

    Write-Host "PHASE2_WINDOWS_RELEASE_TEST=PASS"
    Write-Host "PACKAGE=$($zip.FullName)"
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
