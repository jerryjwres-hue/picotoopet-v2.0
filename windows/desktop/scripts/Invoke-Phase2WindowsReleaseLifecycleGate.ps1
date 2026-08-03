# 仅用于 CI：将 OneDrive 重定向桌面夹具规范化为 ASCII 路径，避免 pwsh -> Windows PowerShell 5.1 参数代码页降级。
[CmdletBinding()]
param(
    [string]$ReleaseRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sourcePath = Join-Path $PSScriptRoot "Test-Phase2WindowsRelease.ps1"
$tempPath   = Join-Path $PSScriptRoot ".ci-Test-Phase2WindowsRelease-$PID.ps1"
$strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
$utf8Bom    = [System.Text.UTF8Encoding]::new($true)

try {
    $content = [System.IO.File]::ReadAllText($sourcePath, $strictUtf8)
    $localizedFixture = 'redirected-OneDrive\User\OneDrive\桌面'
    $asciiFixture     = 'redirected-OneDrive\User\OneDrive\Desktop'
    if (-not $content.Contains($localizedFixture)) {
        throw "未找到待规范化的 OneDrive 重定向桌面夹具。"
    }

    $normalized = $content.Replace($localizedFixture, $asciiFixture)
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
