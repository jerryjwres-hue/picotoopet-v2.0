#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$reportDirectory = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\Reports'
$logDirectory    = Join-Path $env:LOCALAPPDATA 'PicotooPetV2\Logs'
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$transcript = Join-Path $logDirectory ('windows-bootstrap-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
Start-Transcript -LiteralPath $transcript -Force | Out-Null

try {
    $environment = & (Join-Path $PSScriptRoot 'Detect-ComfyEnvironment.ps1')
    $paths       = & (Join-Path $PSScriptRoot 'Configure-ComfyPaths.ps1') -VerifyOnly:$VerifyOnly
    $models      = & (Join-Path $PSScriptRoot 'Install-VisualModels.ps1') -VerifyOnly:$VerifyOnly
    $auxiliary   = & (Join-Path $PSScriptRoot 'Detect-AuxiliaryTools.ps1')

    $failedModels = @($models | Where-Object { $_.Status -in @('missing', 'hash_mismatch') }).Count
    $pathsReady   = $paths.Status -in @('configured', 'verified')
    $report = [ordered]@{
        SchemaVersion = '2.2.0'
        GeneratedAt   = (Get-Date).ToUniversalTime().ToString('o')
        Mode          = if ($VerifyOnly) { 'verify' } else { 'install' }
        Status        = if ($failedModels -eq 0 -and $pathsReady) { 'ok' } else { 'incomplete' }
        Environment   = $environment
        Paths         = $paths
        Models        = @($models)
        Auxiliary     = $auxiliary
        Log           = $transcript
    }

    $jsonPath = Join-Path $reportDirectory 'windows_setup_report.json'
    $htmlPath = Join-Path $reportDirectory 'windows_setup_report.html'
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

    $rows = @($models | ForEach-Object {
        '<tr><td>{0}</td><td>{1}</td><td>{2}</td></tr>' -f $_.File, $_.Status, $_.Path
    }) -join "`r`n"
    $html = @"
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Picotoo Pet Windows 检测报告</title>
<style>body{font-family:Segoe UI,Microsoft YaHei,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:8px;text-align:left}.ok{font-weight:700}</style></head>
<body><h1>Picotoo Pet V2 Windows 检测与模型安装</h1><p class="ok">状态：$($report.Status)</p>
<p>Comfy Desktop：$($environment.DesktopExecutable)</p><p>ComfyUI API：$($environment.ComfyApi)</p>
<table><thead><tr><th>模型</th><th>状态</th><th>位置</th></tr></thead><tbody>$rows</tbody></table>
<p>详细 JSON：$jsonPath</p><p>日志：$transcript</p></body></html>
"@
    $html | Set-Content -LiteralPath $htmlPath -Encoding UTF8
    Start-Process $htmlPath
}
catch {
    $errorPath = Join-Path $reportDirectory 'windows_setup_error.txt'
    $_ | Out-String | Set-Content -LiteralPath $errorPath -Encoding UTF8
    Start-Process notepad.exe -ArgumentList $errorPath
    throw
}
finally {
    Stop-Transcript | Out-Null
}
