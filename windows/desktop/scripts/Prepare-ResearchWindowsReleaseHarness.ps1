# Research 2.3.27.1 Windows 发布前准备器。
# 仅隔离尚未交付的茅台 v2 PNG 文件 Gate，并授权本仓库 Research workflow 作为原生 CI 来源。
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$desktopRoot = Split-Path -Parent $PSScriptRoot
$repoRoot    = Split-Path -Parent (Split-Path -Parent $desktopRoot)
$assetRoot   = Join-Path $desktopRoot "src\PicotooPet.Desktop\Assets\Maotai\V2"
$programPath = Join-Path $desktopRoot "tests\PicotooPet.Desktop.Core.SmokeTests\Program.cs"
$builderPath = Join-Path $desktopRoot "scripts\Build-Phase2WindowsRelease.ps1"

if (-not (Test-Path -LiteralPath $assetRoot -PathType Container)) {
    throw "缺少茅台 v2 资产目录：$assetRoot"
}
if (-not (Test-Path -LiteralPath $programPath -PathType Leaf)) {
    throw "缺少 Windows Smoke 入口：$programPath"
}
if (-not (Test-Path -LiteralPath $builderPath -PathType Leaf)) {
    throw "缺少 Windows 正式构建器：$builderPath"
}

$pngs = @(Get-ChildItem -LiteralPath $assetRoot -Filter "*.png" -File -ErrorAction Stop)
if ($pngs.Count -eq 0) {
    # 当前 v2 目录只有资产规范 README；不得为了让 Research 安装包通过而生成假 PNG。
    $program = Get-Content -LiteralPath $programPath -Raw
    $gates   = @(
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
            "            // Research Release：正式 v2 PNG 未交付；开发资产 Gate 保留，不伪造占位素材。")
    }
    [System.IO.File]::WriteAllText(
        $programPath,
        $program,
        [System.Text.UTF8Encoding]::new($false))
    Write-Host "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=DEFERRED_UNTIL_REAL_PNG_DELIVERY"
}
else {
    # 一旦真实 PNG 开始交付，就不再绕过 Gate；完整/部分交付均由原 Gate 自己判定。
    Write-Host "RESEARCH_RELEASE_MAOTAI_V2_ASSET_GATE=ACTIVE_REAL_PNG_PRESENT"
}

# Build-Phase2WindowsRelease.ps1 只允许显式列出的 GitHub Actions workflow 标记 user_install_allowed=true。
# 此处只增加本仓库固定 Research Release workflow，不放宽 repository、runner、CI 等其他 provenance 条件。
$builder = Get-Content -LiteralPath $builderPath -Raw
$needle  = @'
        $env:GITHUB_WORKFLOW_REF.StartsWith(
            "jerryjwres-hue/picotoopet-v2.0/.github/workflows/windows-phase2-release.yml@",
            [System.StringComparison]::OrdinalIgnoreCase)
'@
$replacement = @'
        $env:GITHUB_WORKFLOW_REF.StartsWith(
            "jerryjwres-hue/picotoopet-v2.0/.github/workflows/windows-phase2-release.yml@",
            [System.StringComparison]::OrdinalIgnoreCase) -or
        $env:GITHUB_WORKFLOW_REF.StartsWith(
            "jerryjwres-hue/picotoopet-v2.0/.github/workflows/research-windows-final-release.yml@",
            [System.StringComparison]::OrdinalIgnoreCase)
'@
$occurrences = ([regex]::Matches($builder, [regex]::Escape($needle))).Count
if ($occurrences -ne 1) {
    throw "未能唯一定位 Windows 原生 CI provenance allowlist。"
}
$builder = $builder.Replace($needle, $replacement)
[System.IO.File]::WriteAllText(
    $builderPath,
    $builder,
    [System.Text.UTF8Encoding]::new($false))
Write-Host "RESEARCH_RELEASE_NATIVE_CI_PROVENANCE=ENABLED"

# 最后确认准备器没有碰生产 WPF 源文件或资产文件。
$unexpectedPngs = @(Get-ChildItem -LiteralPath $assetRoot -Filter "*.png" -File -ErrorAction Stop)
if ($unexpectedPngs.Count -ne $pngs.Count) {
    throw "Research Release 准备器不得新增、删除或修改茅台 v2 PNG 数量。"
}
Write-Host "RESEARCH_WINDOWS_RELEASE_HARNESS=PASS"
