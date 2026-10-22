#requires -Version 5.1
<#
.SYNOPSIS
  PicotooPet P0 #91: passive Windows Comfy/Wan evidence inspection.
.DESCRIPTION
  GET-only Comfy API, local file reads and command capability queries.
  Does NOT launch Comfy, install, download, create paths, POST /prompt or use the GPU for inference.
  Run only on an already safely powered/authorized Windows machine.
#>
[CmdletBinding()]
param(
    [string]$ManifestPath = (Join-Path $PSScriptRoot '..\..\windows\bootstrap\model_manifest.json'),
    [string]$ComfyDataRoot = '',
    [string[]]$PromptIds = @(),
    [string[]]$WebmPaths = @(),
    [switch]$SkipModelHashes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$checks = New-Object 'System.Collections.Generic.List[object]'
$api = 'http://127.0.0.1:8188'

# Report only: PASS means that ONE check has actual passive evidence, never a real render PASS.
function Add-Check {
    param([string]$Name, [string]$Status, [string]$Detail, [object]$Evidence = $null)
    $script:checks.Add([pscustomobject]@{
        Name     = $Name
        Status   = $Status
        Detail   = $Detail
        Evidence = $Evidence
    })
}

# Fixed localhost GET path. There are no POST, service-start or configuration writes.
function Read-Comfy {
    param([string]$Route)
    return Invoke-RestMethod -Uri ($script:api + $Route) -Method Get -TimeoutSec 8 -ErrorAction Stop
}

# Comfy service and native graph inventory are independent readiness criteria.
$info = $null
try {
    $stats = Read-Comfy '/system_stats'
    Add-Check 'COMFY_SYSTEM_STATS' 'PASS' 'GET /system_stats reachable' ([pscustomobject]@{
        System  = $stats.system
        Devices = $stats.devices
    })
}
catch {
    Add-Check 'COMFY_SYSTEM_STATS' 'BLOCKED' 'Already-running Comfy API unavailable; do not start it here'
}

try {
    $info = Read-Comfy '/object_info'
    $requiredNodes = @('UNETLoader','CLIPLoader','VAELoader','ModelSamplingSD3','CLIPTextEncode','Wan22ImageToVideoLatent','KSampler','VAEDecode','SaveWEBM')
    $missingNodes = @($requiredNodes | Where-Object { $info.PSObject.Properties.Name -notcontains $_ })
    if ($missingNodes.Count -eq 0) {
        Add-Check 'T2V_NATIVE_NODES' 'PASS' 'All nine T2V class names exposed' $requiredNodes
    }
    else {
        Add-Check 'T2V_NATIVE_NODES' 'BLOCKED' 'Missing T2V nodes' $missingNodes
    }
    Add-Check 'I2V_LOAD_IMAGE' $(if ($info.PSObject.Properties.Name -contains 'LoadImage') {'PASS'} else {'BLOCKED'}) 'The current production preflight requires LoadImage even for T2V' $null
}
catch {
    Add-Check 'T2V_NATIVE_NODES' 'BLOCKED' 'GET /object_info unavailable or invalid' $null
    Add-Check 'I2V_LOAD_IMAGE' 'UNVERIFIED' 'No native-node response' $null
}

# The actual Comfy choices must expose pinned names, not just filenames on disk.
$pins = @(
    @{ Node = 'UNETLoader'; Slot = 'unet_name';  File = 'wan2.2_ti2v_5B_fp16.safetensors' },
    @{ Node = 'CLIPLoader'; Slot = 'clip_name';  File = 'umt5_xxl_fp8_e4m3fn_scaled.safetensors' },
    @{ Node = 'VAELoader'; Slot = 'vae_name';    File = 'wan2.2_vae.safetensors' }
)
foreach ($pin in $pins) {
    $status = 'UNVERIFIED'
    $detail = 'object_info was not available'
    if ($null -ne $info) {
        try {
            $node = $info.PSObject.Properties[$pin.Node].Value
            $slot = $node.input.required.PSObject.Properties[$pin.Slot].Value
            $choices = @($slot[0] | ForEach-Object { $_ })
            $status = if ($choices -contains $pin.File) { 'PASS' } else { 'BLOCKED' }
            $detail = 'Compare Comfy loader dropdown values with pinned model name'
        }
        catch {
            $status = 'BLOCKED'
            $detail = 'Loader slot/choices are absent or incompatible'
        }
    }
    Add-Check ('COMFY_CHOICE_' + $pin.Node) $status $detail $pin.File
}

# Check fixed enum options as well as class existence; incompatible node signatures block the exact frozen graph.
$enumPins = @(
    @{ Node = 'CLIPLoader'; Slot = 'type';         Value = 'wan' },
    @{ Node = 'UNETLoader'; Slot = 'weight_dtype'; Value = 'default' },
    @{ Node = 'KSampler';   Slot = 'sampler_name'; Value = 'uni_pc' },
    @{ Node = 'KSampler';   Slot = 'scheduler';    Value = 'simple' },
    @{ Node = 'SaveWEBM';   Slot = 'codec';        Value = 'vp9' }
)
foreach ($enum in $enumPins) {
    $status = 'UNVERIFIED'
    if ($null -ne $info) {
        try {
            $node = $info.PSObject.Properties[$enum.Node].Value
            $field = $node.input.required.PSObject.Properties[$enum.Slot]
            if ($null -eq $field -and $null -ne $node.input.PSObject.Properties['optional']) {
                $field = $node.input.optional.PSObject.Properties[$enum.Slot]
            }
            if ($null -eq $field) { throw 'Comfy enum slot missing' }
            $slot = $field.Value
            $options = @($slot[0] | ForEach-Object { $_ })
            $status = if ($options -contains $enum.Value) { 'PASS' } else { 'BLOCKED' }
        }
        catch {
            $status = 'BLOCKED'
        }
    }
    Add-Check ('COMFY_ENUM_' + $enum.Node + '_' + $enum.Slot) $status 'Exact pinned API node enum option' $enum.Value
}

# Queue/history queries do not reserve tasks, claim jobs or submit new graph work.
try {
    $queue = Read-Comfy '/queue'
    $running = if ($null -eq $queue.queue_running) { 0 } else { @($queue.queue_running).Count }
    $pending = if ($null -eq $queue.queue_pending) { 0 } else { @($queue.queue_pending).Count }
    Add-Check 'COMFY_QUEUE_READ' 'PASS' 'Queue observed; nonempty is not an invitation to interrupt' ([pscustomobject]@{
        Running = $running
        Pending = $pending
    })
    if ($running -gt 0 -or $pending -gt 0) {
        Add-Check 'GPU_QUEUE_IDLE' 'BLOCKED' 'Existing prompts must be accounted for before a new production run' $null
    }
    else {
        Add-Check 'GPU_QUEUE_IDLE' 'PASS' 'No entries in currently returned queue' $null
    }
}
catch {
    Add-Check 'COMFY_QUEUE_READ' 'BLOCKED' 'GET /queue unavailable' $null
    Add-Check 'GPU_QUEUE_IDLE' 'UNVERIFIED' 'Queue unknown' $null
}

try {
    $recent = Read-Comfy '/history?max_items=50'
    Add-Check 'COMFY_RECENT_HISTORY' 'PASS' 'At most 50 retained entries; absence is NOT proof of no prior POST' ([pscustomobject]@{
        Count = @($recent.PSObject.Properties.Name).Count
        Ids   = @($recent.PSObject.Properties.Name)
    })
}
catch {
    Add-Check 'COMFY_RECENT_HISTORY' 'UNVERIFIED' 'GET /history?max_items=50 unavailable' $null
}

foreach ($promptId in $PromptIds) {
    if ($promptId -notmatch '^[A-Za-z0-9-]{1,200}$') {
        Add-Check 'PROMPT_HISTORY' 'BLOCKED' 'Reject noncanonical supplied prompt id' $promptId
        continue
    }
    try {
        $history = Read-Comfy ('/history/' + [uri]::EscapeDataString($promptId))
        $entry = $history.PSObject.Properties[$promptId].Value
        if ($null -eq $entry) {
            Add-Check 'PROMPT_HISTORY' 'UNVERIFIED' 'Prompt not present in retained history' $promptId
        }
        else {
            Add-Check 'PROMPT_HISTORY' 'PASS' 'Read-only bound prompt history; inspect status and outputs before acceptance' ([pscustomobject]@{
                PromptId = $promptId
                Status   = $entry.status
                Outputs  = $entry.outputs
            })
        }
    }
    catch {
        Add-Check 'PROMPT_HISTORY' 'UNVERIFIED' 'Prompt history lookup failed' $promptId
    }
}

# Validate exactly the THREE T2V execution models against committed SHA256 values.
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    Add-Check 'T2V_MODEL_HASHES' 'BLOCKED' 'Pinned model manifest unavailable; supply -ManifestPath for a verified checkout' $ManifestPath
}
else {
    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        foreach ($name in @('wan2.2_ti2v_5B_fp16.safetensors','umt5_xxl_fp8_e4m3fn_scaled.safetensors','wan2.2_vae.safetensors')) {
            $item = @($manifest.models | Where-Object { $_.filename -ceq $name })
            if ($item.Count -ne 1) {
                Add-Check 'T2V_MODEL_HASH' 'BLOCKED' 'Model missing or duplicated in pinned manifest' $name
                continue
            }
            $file = Join-Path (Join-Path ([string]$manifest.model_root) ([string]$item[0].destination)) $name
            if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
                Add-Check 'T2V_MODEL_HASH' 'BLOCKED' 'Pinned model file missing' $file
                continue
            }
            if ($SkipModelHashes) {
                Add-Check 'T2V_MODEL_HASH' 'UNVERIFIED' 'File exists but hashing deliberately skipped' $file
                continue
            }
            $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
            $expected = ([string]$item[0].sha256).ToLowerInvariant()
            Add-Check 'T2V_MODEL_HASH' $(if ($actual -ceq $expected) {'PASS'} else {'BLOCKED'}) 'Exact SHA256 required (not basename/size alone)' ([pscustomobject]@{
                Path     = $file
                Expected = $expected
                Actual   = $actual
            })
        }
    }
    catch {
        Add-Check 'T2V_MODEL_HASHES' 'BLOCKED' 'Cannot parse manifest or read/hash pinned models' $null
    }
}

# The running Comfy data root must be verified independently; no directories are created.
if ([string]::IsNullOrWhiteSpace($ComfyDataRoot)) {
    $config = Join-Path $env:APPDATA 'ComfyUI\config.json'
    if (Test-Path -LiteralPath $config -PathType Leaf) {
        try {
            $ComfyDataRoot = [string]((Get-Content -LiteralPath $config -Raw | ConvertFrom-Json).basePath)
        }
        catch {
            $ComfyDataRoot = ''
        }
    }
}
if (-not [string]::IsNullOrWhiteSpace($ComfyDataRoot) -and (Test-Path -LiteralPath $ComfyDataRoot -PathType Container)) {
    $outputRoot = Join-Path $ComfyDataRoot 'output'
    Add-Check 'COMFY_DATA_ROOT' $(if (Test-Path -LiteralPath $outputRoot -PathType Container) {'PASS'} else {'BLOCKED'}) 'Confirm this is the root actually used by the running Comfy instance' $outputRoot
}
else {
    Add-Check 'COMFY_DATA_ROOT' 'UNVERIFIED' 'Use -ComfyDataRoot or inspect documented ProductionLocalEnvironment fallback order' $ComfyDataRoot
}

# The NVIDIA query is a passive snapshot, NOT a measured 3-shot peak or a VRAM guarantee.
$smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
if ($null -ne $smi) {
    try {
        $gpu = @(& $smi.Source --query-gpu=name,driver_version,memory.total,memory.free,memory.used,utilization.gpu,power.draw --format=csv,noheader,nounits 2>$null)
        # ── Exit code 0 is insufficient: nvidia-smi may print N/A or empty VRAM fields. ──
        $validVram = ($gpu.Count -gt 0)
        foreach ($row in $gpu) {
            $fields = @(([string]$row).Split(','))
            if ($fields.Count -ne 7 -or [string]::IsNullOrWhiteSpace($fields[0]) -or
                $fields[2] -notmatch '^\s*[0-9]+(?:\.[0-9]+)?\s*$' -or
                $fields[3] -notmatch '^\s*[0-9]+(?:\.[0-9]+)?\s*$' -or
                $fields[4] -notmatch '^\s*[0-9]+(?:\.[0-9]+)?\s*$') {
                $validVram = $false
                break
            }
            if ([double]::Parse($fields[2], [Globalization.CultureInfo]::InvariantCulture) -le 0) {
                $validVram = $false
                break
            }
        }
        Add-Check 'NVIDIA_GPU_INVENTORY' $(if ($LASTEXITCODE -eq 0 -and $validVram) {'PASS'} else {'UNVERIFIED'}) 'VRAM fields must be numeric; snapshot never proves render capacity or GPU seconds' $gpu
    }
    catch {
        Add-Check 'NVIDIA_GPU_INVENTORY' 'UNVERIFIED' 'nvidia-smi failed' $null
    }
}
else {
    Add-Check 'NVIDIA_GPU_INVENTORY' 'UNVERIFIED' 'nvidia-smi not on PATH' $null
}

# ffmpeg/ffprobe help/capability commands and per-file probes do not encode media.
$ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe.exe -ErrorAction SilentlyContinue
if ($null -ne $ffmpeg) {
    try {
        $encoders = @(& $ffmpeg.Source -hide_banner -encoders 2>&1) -join [Environment]::NewLine
        Add-Check 'FFMPEG_LIBX264' $(if ($encoders -match '(^|\s)libx264(\s|$)') {'PASS'} else {'BLOCKED'}) 'libx264 encoder capability (no encoding executed)' $ffmpeg.Source
    }
    catch {
        Add-Check 'FFMPEG_LIBX264' 'BLOCKED' 'ffmpeg -encoders failed' $null
    }
}
else {
    Add-Check 'FFMPEG_LIBX264' 'BLOCKED' 'ffmpeg.exe not on PATH' $null
}
Add-Check 'FFPROBE_FOUND' $(if ($null -ne $ffprobe) {'PASS'} else {'BLOCKED'}) 'ffprobe needed to examine real WebM/MP4 streams' $(if ($null -ne $ffprobe) {$ffprobe.Source} else {$null})

foreach ($path in $WebmPaths) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Check 'WEBM_EVIDENCE' 'BLOCKED' 'Supplied existing file missing' $path
        continue
    }
    if ($null -eq $ffprobe) {
        Add-Check 'WEBM_EVIDENCE' 'UNVERIFIED' 'ffprobe absent; do not infer codec/duration from extension' $path
        continue
    }
    try {
        $item = Get-Item -LiteralPath $path
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Add-Check 'WEBM_EVIDENCE' 'BLOCKED' 'Reparse-point input is forbidden' $path
            continue
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        $probe = & $ffprobe.Source -v error -show_entries 'format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,nb_frames,r_frame_rate' -of json -i $item.FullName
        if ($LASTEXITCODE -ne 0) { throw 'ffprobe failed' }
        Add-Check 'WEBM_EVIDENCE' 'PASS' 'Observed existing bytes/stream; still compare to exact Core task receipt' ([pscustomobject]@{
            Path   = $item.FullName
            Bytes  = $item.Length
            Sha256 = $hash
            Probe  = ($probe -join [Environment]::NewLine | ConvertFrom-Json)
        })
    }
    catch {
        Add-Check 'WEBM_EVIDENCE' 'BLOCKED' 'Hash/ffprobe failed' $path
    }
}

# Do not equate passive readiness with actual unperformed rendering or visual QA.
$blocked = @($checks | Where-Object { $_.Status -eq 'BLOCKED' }).Count
$unverified = @($checks | Where-Object { $_.Status -eq 'UNVERIFIED' }).Count
[pscustomobject]@{
    SchemaVersion        = '1.0'
    CandidateSha         = 'b6230da62eb803e9a7be840374feeb481a657c3a'
    Scope                = 'READ_ONLY_NO_POST_NO_GPU_INFERENCE'
    InspectedAtUtc       = (Get-Date).ToUniversalTime().ToString('o')
    PreflightDisposition = if ($blocked -gt 0) { 'BLOCKED' } elseif ($unverified -gt 0) { 'UNVERIFIED' } else { 'PASS_PASSIVE_ONLY' }
    LiveThreeShotRender  = 'UNVERIFIED'
    GpuBusySeconds       = 'UNVERIFIED'
    Checks               = $checks.ToArray()
} | ConvertTo-Json -Depth 14
