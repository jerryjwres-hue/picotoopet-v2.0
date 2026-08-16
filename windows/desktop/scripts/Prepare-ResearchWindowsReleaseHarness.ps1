# Research 2.3.27.1 Windows 发布前完整性 Gate。
# 不修改 Smoke 入口、不伪造资产、不运行时改写发布 provenance；真实茅台 v2 资产未交付时直接阻塞正式包。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$assetRoot   = Join-Path $desktopRoot "src\PicotooPet.Desktop\Assets\Maotai\V2"

if (-not (Test-Path -LiteralPath $assetRoot -PathType Container)) {
    Write-Host "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=BLOCKED_MISSING_REAL_ASSETS"
    throw "缺少茅台 v2 资产目录：$assetRoot"
}

$pngs = @(Get-ChildItem -LiteralPath $assetRoot -Filter "*.png" -File -ErrorAction Stop)
if ($pngs.Count -eq 0) {
    Write-Host "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=BLOCKED_MISSING_REAL_ASSETS"
    throw "茅台 v2 正式 PNG 尚未交付；Research Windows 正式安装包不得通过修改测试入口绕过该验收。"
}

# 这里只做前置存在性判断；完整、部分或错误资产均继续交给原生 WPF Smoke 的
# MaotaiNaturalMotionV2AcceptanceSmokeTests / MaotaiAssetPixelValidationSmokeTests 严格判定。
Write-Host "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=ACTIVE_REAL_PNG_PRESENT"
Write-Host "RESEARCH_WINDOWS_RELEASE_HARNESS=PASS"
