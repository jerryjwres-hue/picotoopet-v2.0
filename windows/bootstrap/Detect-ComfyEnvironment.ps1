#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$OutputPath = "",
    [string]$SuppliedDesktopRoot = 'C:\zhaoyang lin\opc\Comfy Desktop'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-ComfyDataRoot {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    $hasModels      = Test-Path -LiteralPath (Join-Path $Path 'models') -PathType Container
    $hasCustomNodes = Test-Path -LiteralPath (Join-Path $Path 'custom_nodes') -PathType Container
    $hasMain        = Test-Path -LiteralPath (Join-Path $Path 'main.py') -PathType Leaf
    return ($hasModels -or $hasCustomNodes -or $hasMain)
}

function Get-NvidiaSummary {
    $command = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return [ordered]@{ Present = $false; Detail = 'nvidia-smi not found' }
    }
    try {
        $value = & $command.Source --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null
        return [ordered]@{ Present = $true; Detail = ($value -join '; ') }
    }
    catch {
        return [ordered]@{ Present = $true; Detail = 'nvidia-smi query failed' }
    }
}

$desktopExe              = Join-Path $SuppliedDesktopRoot 'Comfy Desktop.exe'
$desktopResource         = Join-Path $SuppliedDesktopRoot 'resources\ComfyUI'
$ReadOnlyDesktopResource = $desktopResource
$desktopConfigPath       = Join-Path $env:APPDATA 'ComfyUI\config.json'
$desktopBasePath         = $null
$candidates              = New-Object System.Collections.Generic.List[string]

# Comfy Desktop 把用户选择的数据根目录写入 config.json 的 basePath。
if (Test-Path -LiteralPath $desktopConfigPath -PathType Leaf) {
    try {
        $desktopConfig = Get-Content -LiteralPath $desktopConfigPath -Raw | ConvertFrom-Json
        if ($desktopConfig.PSObject.Properties.Name -contains 'basePath') {
            $desktopBasePath = [string]$desktopConfig.basePath
        }
    }
    catch {
        $desktopBasePath = $null
    }
}

$knownCandidates = @(
    $desktopBasePath,
    $SuppliedDesktopRoot,
    (Join-Path $env:APPDATA 'ComfyUI'),
    (Join-Path $env:LOCALAPPDATA 'ComfyUI'),
    (Join-Path $env:USERPROFILE 'ComfyUI'),
    'D:\ComfyUI',
    'D:\PicotooPet\ComfyUI',
    'E:\ComfyUI'
)

foreach ($candidate in $knownCandidates) {
    if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
    if (Test-ComfyDataRoot -Path $candidate) {
        if ($candidate -notlike "$ReadOnlyDesktopResource*") {
            $candidates.Add((Resolve-Path -LiteralPath $candidate).Path)
        }
    }
}

$configPath = Join-Path $env:APPDATA 'ComfyUI\extra_models_config.yaml'
$apiState   = 'offline'
try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/object_info' -TimeoutSec 2 -Method Get
    $apiState = 'online'
}
catch {
    $apiState = 'offline'
}

$result = [ordered]@{
    SchemaVersion            = '2.2.0'
    CheckedAt                = (Get-Date).ToUniversalTime().ToString('o')
    SuppliedDesktopRoot      = $SuppliedDesktopRoot
    DesktopExecutableExists = (Test-Path -LiteralPath $desktopExe -PathType Leaf)
    DesktopExecutable       = $desktopExe
    ReadOnlyDesktopResource = $ReadOnlyDesktopResource
    DesktopConfigPath       = $desktopConfigPath
    DesktopBasePath         = $desktopBasePath
    ResourceModification    = 'FORBIDDEN'
    DataRootCandidates      = @($candidates | Select-Object -Unique)
    ExtraModelsConfig       = $configPath
    ExtraModelsConfigExists = (Test-Path -LiteralPath $configPath -PathType Leaf)
    ComfyApi                 = $apiState
    Nvidia                   = Get-NvidiaSummary
    PowerShellVersion       = $PSVersionTable.PSVersion.ToString()
    Drives                   = @(
        Get-PSDrive -PSProvider FileSystem | ForEach-Object {
            [ordered]@{
                Name      = $_.Name
                Root      = $_.Root
                FreeBytes = $_.Free
                UsedBytes = $_.Used
            }
        }
    )
}

if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $parent = Split-Path -Parent $OutputPath
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
}
$result
