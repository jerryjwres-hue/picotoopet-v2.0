#requires -Version 5.1
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ModelRoot = 'E:\PicotooPet\Models',
    [string]$ConfigPath = (Join-Path $env:APPDATA 'ComfyUI\extra_models_config.yaml'),
    [switch]$VerifyOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$forbiddenFragment = 'resources\ComfyUI'
if ($ConfigPath -like "*$forbiddenFragment*") {
    throw '禁止修改 Comfy Desktop resources\ComfyUI。'
}
if ($ModelRoot -like "*$forbiddenFragment*") {
    throw '模型根目录不能位于 Comfy Desktop resources\ComfyUI。'
}

$modelCategories = @(
    'checkpoints',
    'diffusion_models',
    'text_encoders',
    'vae',
    'clip_vision',
    'loras',
    'controlnet',
    'upscale_models'
)
$beginMarker = '# BEGIN PICOTOO PET V2 MANAGED MODELS'
$endMarker   = '# END PICOTOO PET V2 MANAGED MODELS'
$configExists = Test-Path -LiteralPath $ConfigPath -PathType Leaf
$existing     = if ($configExists) { Get-Content -LiteralPath $ConfigPath -Raw } else { '' }
$yamlRoot     = $ModelRoot.Replace('\', '/')
$managedValid = $configExists -and $existing.Contains($beginMarker) -and `
    $existing.Contains($endMarker) -and $existing.Contains($yamlRoot)
$missingCategories = @(
    $modelCategories | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $ModelRoot $_) -PathType Container)
    }
)

# 验证模式必须完全只读，不创建目录、备份或配置文件。
if ($VerifyOnly) {
    [ordered]@{
        ConfigPath       = $ConfigPath
        ModelRoot        = $ModelRoot
        Categories       = $modelCategories
        MissingCategories = $missingCategories
        ManagedBlockValid = $managedValid
        Status           = if ($managedValid -and $missingCategories.Count -eq 0) {
            'verified'
        }
        else {
            'incomplete'
        }
    }
    return
}

foreach ($category in $modelCategories) {
    New-Item -ItemType Directory -Path (Join-Path $ModelRoot $category) -Force | Out-Null
}

$configDirectory = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
if ($configExists) {
    $backupPath = '{0}.backup-{1}' -f $ConfigPath, (Get-Date -Format 'yyyyMMdd-HHmmss')
    Copy-Item -LiteralPath $ConfigPath -Destination $backupPath -Force
}

$pattern = '(?ms)^' + [regex]::Escape($beginMarker) + '.*?^' + `
    [regex]::Escape($endMarker) + '\s*'
$cleaned = [regex]::Replace($existing, $pattern, '').TrimEnd()
$managed = @"
$beginMarker
picotoopet_v2:
  base_path: $yamlRoot
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
  clip_vision: clip_vision
  loras: loras
  controlnet: controlnet
  upscale_models: upscale_models
$endMarker
"@

$content = if ([string]::IsNullOrWhiteSpace($cleaned)) {
    $managed
}
else {
    "$cleaned`r`n`r`n$managed"
}
if ($PSCmdlet.ShouldProcess($ConfigPath, '写入 Picotoo Pet V2 外部模型路径')) {
    $temporary = "$ConfigPath.partial"
    $content | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $ConfigPath -Force
}

[ordered]@{
    ConfigPath        = $ConfigPath
    ModelRoot         = $ModelRoot
    Categories        = $modelCategories
    MissingCategories = @()
    ManagedBlockValid = $true
    Status            = 'configured'
}
