#requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CommandState {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) { return [ordered]@{ Present = $false; Path = $null } }
    return [ordered]@{ Present = $true; Path = $command.Source }
}

[ordered]@{
    FasterWhisper = [ordered]@{
        Python = Get-CommandState -Name 'python.exe'
        Note   = '独立 Windows Worker 环境在后续 Worker 阶段安装，不复用 ComfyUI Desktop 内置 Python。'
    }
    FFmpeg        = Get-CommandState -Name 'ffmpeg.exe'
    RIFE          = [ordered]@{ Present = $false; Detection = 'pending_worker_connector' }
    RealESRGAN    = [ordered]@{ Present = $false; Detection = 'pending_worker_connector' }
    SAM2          = [ordered]@{ Present = $false; Detection = 'pending_worker_connector' }
}
