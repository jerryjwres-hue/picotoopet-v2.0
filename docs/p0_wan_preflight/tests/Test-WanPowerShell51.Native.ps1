#requires -Version 5.1
<#
.SYNOPSIS
  Real Windows PowerShell 5.1 fail-closed contract tests for G-Wan passive preflight.
.DESCRIPTION
  Starts ONLY a local GET-only mock HttpListener and native capability stubs on
  an ephemeral GitHub-hosted runner. The inspected script is always invoked
  through the genuine Windows powershell.exe -File boundary.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$preflight = Join-Path $repoRoot 'docs\p0_wan_preflight\Test-WanReadOnlyPreflight.ps1'
$root = Join-Path $env:RUNNER_TEMP 'p0-wan-ps51-contract'
$ps = Join-Path $PSHOME 'powershell.exe'
if ($PSVersionTable.PSVersion.Major -ne 5 -or -not (Test-Path $ps)) { throw 'Requires native Windows PowerShell 5.1' }
if (Test-Path $root) { Remove-Item -LiteralPath $root -Recurse -Force }
New-Item -ItemType Directory -Path $root -Force | Out-Null
$avBin = Join-Path $root 'mock-av'
$gpuBin = Join-Path $root 'mock-gpu'
New-Item -ItemType Directory -Path $avBin,$gpuBin | Out-Null

# Real .exe stubs prove the inspected script's Get-Command and safe capability
# invocation branches; no real ffmpeg, Comfy, model, or GPU is started.
$stub = @'
using System;
using System.IO;
class ToolStub {
    static int Main(string[] args) {
        string name = Path.GetFileNameWithoutExtension(Environment.GetCommandLineArgs()[0]).ToLowerInvariant();
        if (name == "ffmpeg") {
            Console.WriteLine("Encoders:");
            Console.WriteLine(" V..... libx264             libx264 H.264 / AVC");
        } else if (name == "ffprobe") {
            if (Array.IndexOf(args, "-i") >= 0) {
                Console.WriteLine("{\"format\":{\"duration\":\"4.04\",\"format_name\":\"matroska,webm\"}}");
            } else Console.WriteLine("ffprobe mock version");
        } else if (name == "nvidia-smi") {
            if (Environment.GetEnvironmentVariable("WAN_TEST_GPU_INVALID") == "1")
                Console.WriteLine("Mock GPU, 555.01, N/A, N/A, N/A, 0, 18.0");
            else
                Console.WriteLine("Mock GPU, 555.01, 16384, 14000, 2384, 0, 18.0");
        }
        return 0;
    }
}
'@
Add-Type -TypeDefinition $stub -OutputAssembly (Join-Path $avBin 'ffmpeg.exe') -OutputType ConsoleApplication
Copy-Item (Join-Path $avBin 'ffmpeg.exe') (Join-Path $avBin 'ffprobe.exe')
Copy-Item (Join-Path $avBin 'ffmpeg.exe') (Join-Path $gpuBin 'nvidia-smi.exe')
$basePath = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"

# Mirror only the exact Comfy object_info fields inspected by the production
# read-only script, not the worker/production graph implementation.
$objectInfo = @'
{
 "UNETLoader":{"input":{"required":{"unet_name":[["wan2.2_ti2v_5B_fp16.safetensors"],{}],"weight_dtype":[["default"],{}]}}},
 "CLIPLoader":{"input":{"required":{"clip_name":[["umt5_xxl_fp8_e4m3fn_scaled.safetensors"],{}],"type":[["wan"],{}]}}},
 "VAELoader":{"input":{"required":{"vae_name":[["wan2.2_vae.safetensors"],{}]}}},
 "ModelSamplingSD3":{"input":{"required":{}}},
 "CLIPTextEncode":{"input":{"required":{}}},
 "Wan22ImageToVideoLatent":{"input":{"required":{}}},
 "KSampler":{"input":{"required":{"sampler_name":[["uni_pc"],{}],"scheduler":[["simple"],{}]}}},
 "VAEDecode":{"input":{"required":{}}},
 "SaveWEBM":{"input":{"required":{"codec":[["vp9"],{}]}}},
 "LoadImage":{"input":{"required":{}}}
}
'@
$statePath = Join-Path $root 'mock-state.txt'
$logPath = Join-Path $root 'http-methods.log'
Set-Content -LiteralPath $statePath -Value 'baseline' -Encoding Ascii
Set-Content -LiteralPath $logPath -Value '' -Encoding Ascii
$server = $null
$pass = 0
try {
    function New-Fixture {
        param([string]$Name,[switch]$MissingEncoder,[switch]$MissingVae,[switch]$BadSha)
        $caseRoot = Join-Path $root $Name
        $modelRoot = Join-Path $caseRoot 'models'
        $comfyRoot = Join-Path $caseRoot 'comfy'
        foreach ($dir in @('diffusion_models','text_encoders','vae')) {
            New-Item -ItemType Directory -Path (Join-Path $modelRoot $dir) -Force | Out-Null
        }
        New-Item -ItemType Directory -Path (Join-Path $comfyRoot 'output') -Force | Out-Null
        $specs = @(
            @{filename='wan2.2_ti2v_5B_fp16.safetensors'; destination='diffusion_models'},
            @{filename='umt5_xxl_fp8_e4m3fn_scaled.safetensors'; destination='text_encoders'},
            @{filename='wan2.2_vae.safetensors'; destination='vae'}
        )
        $models = @()
        foreach ($spec in $specs) {
            $path = Join-Path (Join-Path $modelRoot $spec.destination) $spec.filename
            [IO.File]::WriteAllText($path, 'test fixture ' + $spec.filename, [Text.Encoding]::UTF8)
            $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            $models += @{ filename=$spec.filename; destination=$spec.destination; sha256=$sha }
            if (($MissingEncoder -and $spec.destination -eq 'text_encoders') -or
                ($MissingVae -and $spec.destination -eq 'vae')) {
                Remove-Item -LiteralPath $path -Force
            }
            elseif ($BadSha -and $spec.destination -eq 'diffusion_models') {
                [IO.File]::AppendAllText($path, 'tampered')
            }
        }
        $manifest = Join-Path $caseRoot 'manifest.json'
        @{model_root=$modelRoot;models=$models} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifest -Encoding UTF8
        return [pscustomobject]@{Home=$caseRoot; Manifest=$manifest; Comfy=$comfyRoot}
    }
    function Fingerprint {
        param([string]$caseRoot)
        return @((Get-ChildItem -LiteralPath $caseRoot -Recurse -Force -File | Sort-Object FullName |
            ForEach-Object { $_.FullName.Substring($caseRoot.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }) -join [Environment]::NewLine)
    }
    function Check {
        param($Report,[string]$Name,[string]$Status)
        $found = @($Report.Checks | Where-Object { $_.Name -eq $Name -and $_.Status -eq $Status })
        if ($found.Count -lt 1) { throw "Expected $Name=$Status; actual $(ConvertTo-Json @($Report.Checks | Where-Object Name -eq $Name) -Compress)" }
    }
    function Run-Case {
        param([string]$Name,[string]$Mode,[string]$ExpectedDisposition,
              [hashtable]$Expect,[switch]$MissingEncoder,[switch]$MissingVae,[switch]$BadSha,
              [switch]$ExistingHistory)
        $fixture = New-Fixture $Name -MissingEncoder:$MissingEncoder -MissingVae:$MissingVae -BadSha:$BadSha
        Set-Content -LiteralPath $statePath -Value $Mode -Encoding Ascii
        Set-Content -LiteralPath $logPath -Value '' -Encoding Ascii
        $originalPath = $env:PATH
        if ($Mode -eq 'bad_vram') { $env:WAN_TEST_GPU_INVALID = '1' }
        else { Remove-Item Env:WAN_TEST_GPU_INVALID -ErrorAction SilentlyContinue }
        if ($Mode -eq 'ffmpeg_missing') { $env:PATH = "$gpuBin;$basePath" }
        elseif ($Mode -eq 'gpu_missing') { $env:PATH = "$avBin;$basePath" }
        else { $env:PATH = "$gpuBin;$avBin;$basePath" }
        $before = Fingerprint $fixture.Home
        $prodDir = Join-Path $fixture.Comfy 'output\PicotooPet\production'
        if (Test-Path -LiteralPath $prodDir) { throw "Pre-existing production dir in fixture: $prodDir" }
        try {
            $argv = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
                $preflight,'-ManifestPath',$fixture.Manifest,'-ComfyDataRoot',$fixture.Comfy)
            if ($ExistingHistory) { $argv += @('-PromptIds','known-prompt-id') }
            $raw = (& $ps @argv 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) { throw "powershell.exe -File exited $LASTEXITCODE : $raw" }
            try { $report = $raw | ConvertFrom-Json } catch { throw "Not valid JSON: $raw" }
            if ($report.PreflightDisposition -ne $ExpectedDisposition) {
                throw "Disposition expected $ExpectedDisposition, got $($report.PreflightDisposition): $raw"
            }
            foreach ($key in $Expect.Keys) { Check $report $key $Expect[$key] }
            if ($report.Scope -ne 'READ_ONLY_NO_POST_NO_GPU_INFERENCE' -or $report.LiveThreeShotRender -ne 'UNVERIFIED') {
                throw 'Passive scope or live render state falsified'
            }
            $after = Fingerprint $fixture.Home
            if ($before -cne $after) { throw "Read-only fixture modified in case $Name" }
            if (Test-Path -LiteralPath $prodDir) { throw "Production directory created by inspected script: $prodDir" }
            $methods = @(Get-Content -LiteralPath $logPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
            foreach ($line in $methods) {
                if ($line -notmatch '^GET /(system_stats|object_info|queue|history(?:\?max_items=50|/known-prompt-id)?)$') {
                    throw "Non-GET or unapproved endpoint contacted: $line"
                }
            }
            Write-Host "WAN_PS51_CASE $Name=PASS disposition=$($report.PreflightDisposition) reads=$($methods.Count)"
            $script:pass++
        }
        finally {
            $env:PATH = $originalPath
            Remove-Item Env:WAN_TEST_GPU_INVALID -ErrorAction SilentlyContinue
        }
    }

    # Offline is tested without starting ANY listener at 8188.
    Run-Case 'offline' 'offline' 'BLOCKED' @{
        COMFY_SYSTEM_STATS='BLOCKED'; T2V_NATIVE_NODES='BLOCKED'; GPU_QUEUE_IDLE='UNVERIFIED'
    }

    # Only a fake local GET server; no Comfy executable or model process is launched.
    $server = Start-Job -ArgumentList $statePath,$logPath,$objectInfo -ScriptBlock {
        param($state,$log,$infoJson)
        $ErrorActionPreference = 'Stop'
        $listener = New-Object System.Net.HttpListener
        $listener.Prefixes.Add('http://127.0.0.1:8188/')
        $listener.Start()
        try {
            while ($listener.IsListening) {
                $context = $listener.GetContext()
                $mode = (Get-Content -LiteralPath $state -Raw).Trim()
                $route = $context.Request.Url.PathAndQuery
                Add-Content -LiteralPath $log -Value "$($context.Request.HttpMethod) $route" -Encoding Ascii
                $body = '{}'
                $status = 200
                switch -Regex ($route) {
                    '^/system_stats$' {
                        $body = '{"system":{"os":"windows","comfyui_version":"mock"},"devices":[{"name":"mock-nvidia"}]}'
                        break
                    }
                    '^/object_info$' {
                        $body = $infoJson
                        if ($mode -eq 'missing_savewebm') {
                            $body = $body -replace '(?s),\s*"SaveWEBM"\s*:\s*\{"input":\{"required":\{"codec":\[\["vp9"\],\{\}\]\}\}\}', ''
                        }
                        if ($mode -eq 'wrong_dropdown') {
                            $body = $body.Replace('wan2.2_ti2v_5B_fp16.safetensors','different-model.safetensors')
                        }
                        break
                    }
                    '^/queue$' {
                        $body = '{"queue_running":[],"queue_pending":[]}'
                        break
                    }
                    '^/history\?max_items=50$' {
                        $body = '{"known-prompt-id":{"status":{"completed":true},"outputs":{}}}'
                        break
                    }
                    '^/history/known-prompt-id$' {
                        $body = '{"known-prompt-id":{"status":{"completed":true},"outputs":{}}}'
                        break
                    }
                    default { $status = 404 }
                }
                $bytes = [Text.Encoding]::UTF8.GetBytes($body)
                $context.Response.StatusCode = $status
                $context.Response.ContentType = 'application/json'
                $context.Response.ContentLength64 = $bytes.Length
                $context.Response.OutputStream.Write($bytes,0,$bytes.Length)
                $context.Response.Close()
            }
        }
        finally { $listener.Stop(); $listener.Close() }
    }
    # Explicitly wait for local test fixture readiness, not a user service.
    $ready = $false
    for ($i=0;$i -lt 40;$i++) {
        if ($server.State -eq 'Failed') { throw "Mock server failed: $(Receive-Job $server)" }
        try {
            $null = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8188/queue' -TimeoutSec 1
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready) { throw "GET-only mock listener could not bind to 8188: $(Receive-Job $server -Keep)" }

    Run-Case 'healthy_mock' 'baseline' 'PASS_PASSIVE_ONLY' @{
        COMFY_SYSTEM_STATS='PASS'; T2V_NATIVE_NODES='PASS'; COMFY_CHOICE_UNETLoader='PASS';
        COMFY_CHOICE_CLIPLoader='PASS'; COMFY_CHOICE_VAELoader='PASS'; GPU_QUEUE_IDLE='PASS';
        COMFY_RECENT_HISTORY='PASS'; T2V_MODEL_HASH='PASS'; NVIDIA_GPU_INVENTORY='PASS';
        FFMPEG_LIBX264='PASS'; FFPROBE_FOUND='PASS'; PROMPT_HISTORY='PASS'
    } -ExistingHistory
    Run-Case 'missing_savewebm' 'missing_savewebm' 'BLOCKED' @{
        T2V_NATIVE_NODES='BLOCKED'; COMFY_ENUM_SaveWEBM_codec='BLOCKED'
    }
    Run-Case 'wrong_dropdown' 'wrong_dropdown' 'BLOCKED' @{
        T2V_NATIVE_NODES='PASS'; COMFY_CHOICE_UNETLoader='BLOCKED'
    }
    Run-Case 'missing_vae' 'baseline' 'BLOCKED' @{T2V_MODEL_HASH='BLOCKED'} -MissingVae
    Run-Case 'missing_encoder' 'baseline' 'BLOCKED' @{T2V_MODEL_HASH='BLOCKED'} -MissingEncoder
    Run-Case 'mismatched_sha' 'baseline' 'BLOCKED' @{T2V_MODEL_HASH='BLOCKED'} -BadSha
    Run-Case 'no_libx264' 'ffmpeg_missing' 'BLOCKED' @{
        FFMPEG_LIBX264='BLOCKED'; FFPROBE_FOUND='BLOCKED'; NVIDIA_GPU_INVENTORY='PASS'
    }
    Run-Case 'unknown_vram' 'gpu_missing' 'UNVERIFIED' @{
        NVIDIA_GPU_INVENTORY='UNVERIFIED'; FFMPEG_LIBX264='PASS'; GPU_QUEUE_IDLE='PASS'
    }
    Run-Case 'invalid_vram_payload' 'bad_vram' 'UNVERIFIED' @{
        NVIDIA_GPU_INVENTORY='UNVERIFIED'; FFMPEG_LIBX264='PASS'; GPU_QUEUE_IDLE='PASS'
    }
    Write-Host "WAN_PS51_RESULT=PASS cases=$pass/10 WindowsPowerShell=$($PSVersionTable.PSVersion)"
}
finally {
    if ($null -ne $server) { Stop-Job $server -ErrorAction SilentlyContinue; Remove-Job $server -Force -ErrorAction SilentlyContinue }
}
