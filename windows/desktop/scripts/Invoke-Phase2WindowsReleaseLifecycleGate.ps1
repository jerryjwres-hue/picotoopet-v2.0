# 仅用于 CI：规范化 PowerShell 5.1 夹具路径，并让正式包断言读取唯一产品版本源。
[CmdletBinding()]
param(
    [string]$ReleaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sourcePath = Join-Path $PSScriptRoot "Test-Phase2WindowsRelease.ps1"
$tempPath   = Join-Path $PSScriptRoot ".ci-Test-Phase2WindowsRelease-$PID.ps1"
$versionPath = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..\..\..\src\picotoopet_core\product-version.txt"))
$strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
$utf8Bom    = [System.Text.UTF8Encoding]::new($true)

try {
    $content = [System.IO.File]::ReadAllText($sourcePath, $strictUtf8)
    $expectedProductVersion = [System.IO.File]::ReadAllText(
        $versionPath,
        $strictUtf8).Trim()
    if ($expectedProductVersion -notmatch '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$') {
        throw "唯一产品版本源不是四段数字：$expectedProductVersion"
    }

    $localizedFixture = 'redirected-OneDrive\User\OneDrive\桌面'
    $asciiFixture     = 'redirected-OneDrive\User\OneDrive\Desktop'
    if (-not $content.Contains($localizedFixture)) {
        throw "未找到待规范化的 OneDrive 重定向桌面夹具。"
    }
    $normalized = $content.Replace($localizedFixture, $asciiFixture)

    $formalManifestAssertion = @'
    if ([string]$manifest.product_version -ne "2.3.6.1") {
        throw "正式包 product_version 不是 2.3.6.1。"
    }
'@
    $formalManifestReplacement = @"
    if ([string]`$manifest.product_version -ne "$expectedProductVersion") {
        throw "正式包 product_version 不是 $expectedProductVersion。"
    }
"@
    if (-not $normalized.Contains($formalManifestAssertion)) {
        throw "未找到正式包 product_version 当前版本断言。"
    }
    $normalized = $normalized.Replace(
        $formalManifestAssertion,
        $formalManifestReplacement)

    $formalSelfTestAssertion = @'
    if ([string]$selfTest.status -ne "pass" -or
        [string]$selfTest.product_version -ne "2.3.6.1") {
        throw "桌面自检报告产品版本不是 pass/2.3.6.1。"
    }
'@
    $formalSelfTestReplacement = @"
    if ([string]`$selfTest.status -ne "pass" -or
        [string]`$selfTest.product_version -ne "$expectedProductVersion") {
        throw "桌面自检报告产品版本不是 pass/$expectedProductVersion。"
    }
"@
    if (-not $normalized.Contains($formalSelfTestAssertion)) {
        throw "未找到桌面自检报告产品版本当前断言。"
    }
    $normalized = $normalized.Replace(
        $formalSelfTestAssertion,
        $formalSelfTestReplacement)

    [System.IO.File]::WriteAllText($tempPath, $normalized, $utf8Bom)

    if ([string]::IsNullOrWhiteSpace($ReleaseRoot)) {
        & $tempPath
    }
    else {
        & $tempPath -ReleaseRoot $ReleaseRoot
    }
}
finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}
