# Windows UI 行为 Gate 专用准备器。
# 只在茅台 v2 真实 PNG 尚未交付（数量严格为 0）时，临时延后两条资产验收 Smoke。
# 不生成假素材、不修改生产 WPF、不改变发布 provenance；一旦任何真实 PNG 出现，原 Gate 自动恢复。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$assetRoot   = Join-Path $desktopRoot "src\PicotooPet.Desktop\Assets\Maotai\V2"
$programPath = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\Program.cs"

if (-not (Test-Path -LiteralPath $assetRoot -PathType Container)) {
    throw "缺少茅台 v2 资产目录：$assetRoot"
}
if (-not (Test-Path -LiteralPath $programPath -PathType Leaf)) {
    throw "缺少 Windows Smoke 入口：$programPath"
}

$beforePngs = @(Get-ChildItem -LiteralPath $assetRoot -Filter "*.png" -File -ErrorAction Stop)
if ($beforePngs.Count -eq 0) {
    $program = Get-Content -LiteralPath $programPath -Raw
    $gates = @(
        "            MaotaiNaturalMotionV2AcceptanceSmokeTests.Run();",
        "            MaotaiAssetPixelValidationSmokeTests.Run();"
    )

    foreach ($gate in $gates) {
        $occurrences = ([regex]::Matches($program, [regex]::Escape($gate))).Count
        if ($occurrences -ne 1) {
            throw "未能唯一定位未交付茅台 v2 资产 Gate：$gate"
        }
        $program = $program.Replace(
            $gate,
            "            // UI Behavior Gate：v2 真实 PNG 尚未交付；资产 Smoke 保留在源码，不伪造素材。")
    }

    [System.IO.File]::WriteAllText(
        $programPath,
        $program,
        [System.Text.UTF8Encoding]::new($false))
    Write-Host "WINDOWS_UI_MAOTAI_V2_ASSET_GATE=DEFERRED_UNTIL_REAL_PNG_DELIVERY"
}
else {
    Write-Host "WINDOWS_UI_MAOTAI_V2_ASSET_GATE=ACTIVE_REAL_PNG_PRESENT"
}

$afterPngs = @(Get-ChildItem -LiteralPath $assetRoot -Filter "*.png" -File -ErrorAction Stop)
if ($afterPngs.Count -ne $beforePngs.Count) {
    throw "UI 行为准备器不得新增或删除茅台 v2 PNG。"
}

Write-Host "WINDOWS_UI_BEHAVIOR_HARNESS=PASS"
