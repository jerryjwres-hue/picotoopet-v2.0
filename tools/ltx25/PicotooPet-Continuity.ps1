#requires -Version 5.1
<#
PicotooPet LTX-2.5 Ingredients continuity pilot (2026-11-10).
Prepare : zero-GPU, real/synthetic reference audit + director packet.
Probe   : read-only authenticated LTX Desktop model/queue readiness.
Pilot   : ONE opt-in 5s/540p Ingredients generation; no auto retry.
Status  : read-only status and successful MP4 export.
Does not modify production Core/Worker, HOLD, frozen Creative Package.
#>
[CmdletBinding()]
param(
    [ValidateSet('Prepare','Probe','Pilot','Status')]
    [string]$Mode = 'Prepare'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

# 固定工程根目录  ：禁止使用 $home（PowerShell 系统只读变量）。
$ltxRoot        = 'D:\opc in D\LTX'
$projectRoot    = Join-Path $ltxRoot '电影项目\茅台晚餐_连续性V2'
$packageRoot    = Join-Path $projectRoot '05_Ingredients连续性实验'
$referenceRoot  = Join-Path $packageRoot 'references'
$receiptRoot    = Join-Path $packageRoot 'receipts'
$clipRoot       = 'D:\AI\LTX25\films\Maotai_Dinner_48s\clips'
$skillsRoot     = Join-Path $ltxRoot '成熟工作流与Skills'
$original       = Join-Path $env:USERPROFILE 'Pictures\PicotooPet\Maotai\Originals\IMG_3576.jpeg'
$originSha      = 'cafe5cfec5e859f416d576809417e4de68f7a3178ee9a532da5f2272c5f9f694'
$bowlReference  = Join-Path $referenceRoot 'S02_BOWL_SYNTHETIC_CANDIDATE.jpg'
$otherBowl      = Join-Path $referenceRoot 'S05_BOWL_DIFFERENT_DO_NOT_MIX.jpg'
$storyboard     = Join-Path $referenceRoot 'DIRECTOR_REFERENCE_COMPARISON.jpg'
$contractFile   = Join-Path $packageRoot 'director_contract.json'
$reportFile     = Join-Path $packageRoot 'source_manifest.json'
$receiptFile    = Join-Path $receiptRoot 'ingredients_pilot.json'
$uncertainFile  = Join-Path $receiptRoot 'ingredients_pilot.POST_UNCERTAIN'
$outputFile     = Join-Path $packageRoot 'Ingredients_OneShot_540p.mp4'
$tokenFile      = Join-Path $env:LOCALAPPDATA 'PicotooPet\LTX25Control\remote-session.dpapi.txt'
$settingsFile   = Join-Path $env:LOCALAPPDATA 'LTXDesktop\settings.json'
$apiBase        = 'http://127.0.0.1:41955'

# 文件系统隔离  ：只新增项目参考板和审计文件，不覆盖已完成影片。
foreach ($folder in @($projectRoot,$packageRoot,$referenceRoot,$receiptRoot)) {
    if (!(Test-Path -LiteralPath $folder -PathType Container)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
}

function Assert-Original {
    # 原始身份锁  ：只有真实茅台原图的已知字节身份才可以进入试验。
    if (!(Test-Path -LiteralPath $original -PathType Leaf)) {
        throw 'STOP=REAL_MAOTAI_ORIGINAL_NOT_FOUND'
    }
    $item = Get-Item -LiteralPath $original
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'STOP=REAL_ORIGINAL_IS_REPARSE_POINT'
    }
    $digest = (Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($digest -ne $originSha) {
        throw 'STOP=REAL_ORIGINAL_SHA_MISMATCH'
    }
    Write-Output 'MAOTAI_SOURCE=VERIFIED_REAL_PHOTO'
}

function Ensure-Frame([string]$src,[string]$sec,[string]$dest) {
    # FFmpeg 取证    ：从已完成生成片截取候选静帧；不修改原始视频。
    if (!(Test-Path -LiteralPath $src -PathType Leaf)) {
        throw ('STOP=REQUIRED_SOURCE_CLIP_MISSING ' + $src)
    }
    if (Test-Path -LiteralPath $dest -PathType Leaf) { return }
    $ffmpeg = (Get-Command ffmpeg.exe -ErrorAction Stop).Source
    $tmp = $dest + '.tmp.jpg'
    if (Test-Path -LiteralPath $tmp) { throw 'STOP=PREVIOUS_UNVERIFIED_FRAME_TEMP' }
    & $ffmpeg -hide_banner -loglevel error -ss $sec -i $src -frames:v 1 -q:v 3 -y $tmp
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $tmp -PathType Leaf)) {
        throw ('STOP=FRAME_EXTRACT_FAILED ' + $src)
    }
    Move-Item -LiteralPath $tmp -Destination $dest
}

function Prepare-Packet {
    Assert-Original
    Ensure-Frame (Join-Path $clipRoot 'S02.mp4') '3.0' $bowlReference
    Ensure-Frame (Join-Path $clipRoot 'S05.mp4') '2.4' $otherBowl

    # 参考对照板  ：真实茅台 / S02 虚构食盆 / S05 不一致食盆；未经审核。
    if (!(Test-Path -LiteralPath $storyboard -PathType Leaf)) {
        $ffmpeg = (Get-Command ffmpeg.exe -ErrorAction Stop).Source
        $graph = '[0:v]scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2[a];[1:v]scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2[b];[2:v]scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2[c];[a][b][c]hstack=inputs=3[v]'
        & $ffmpeg -hide_banner -loglevel error -i $original -i $bowlReference -i $otherBowl -filter_complex $graph -map '[v]' -frames:v 1 -q:v 3 -y $storyboard
        if ($LASTEXITCODE -ne 0) { throw 'STOP=BOARD_RENDER_FAILED' }
    }

    # 成熟 Skill 溯源：使用原版规则设计分镜合同，不伪称 Agent 已运行。
    $skillPaths = @(
        'ai-film-skills\director-agent\SKILL.md',
        'ai-film-skills\ai-storyboard-director\SKILL.md',
        'cinematography\SKILL.md'
    )
    $skills = @()
    foreach ($path in $skillPaths) {
        $full = Join-Path $skillsRoot $path
        if (!(Test-Path -LiteralPath $full -PathType Leaf)) {
            throw ('STOP=MATURE_SKILL_NOT_INSTALLED ' + $full)
        }
        $skills += @{
            path   = $full
            sha256 = (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash.ToLowerInvariant()
            status = 'SOURCE_RULES_PRESENT_NOT_EXECUTED_AS_MODEL_AGENT'
        }
    }

    # 影视合同      ：每一镜都有动机、来源、光轴、声音、动作起止与剪辑动机。
    $story = @(
        @{
            shot_id='A'; purpose='Establish food sound'
            subject_id='BOWL-CANDIDATE-S02'; setting_id='KITCHEN-SYNTHETIC-S02'
            start_reference=$bowlReference; end_state='The canonical S02 bowl is full and remains stationary'
            before_state='Empty canonical bowl on kitchen counter'
            camera='50mm-equivalent close view; static; consistent axis'
            lighting='Warm practical light from frame left, neutral whites'
            action='Dry kibble falls into the ONE matching steel bowl'
            audio='Metallic kibble taps begin before cut to the pet'
            cut_motivation='Acoustic event motivates Maotai looking toward kitchen'
            trust='SYNTHETIC_CREATIVE_LOCATION_AND_BOWL'
        },
        @{
            shot_id='B'; purpose='Carry audible cause into the living room'
            subject_id='BOWL-CANDIDATE-S02'; setting_id='LIVINGROOM-PARTIAL-REAL'
            start_reference=$bowlReference; end_state='The same bowl is visibly set on the wood floor'
            before_state='Filled S02 bowl, one hand enters from established direction'
            camera='Pet-eye-level medium view; static; preserve movement direction'
            lighting='Warm reflected household light matching Maotai reference'
            action='One hand brings the exact S02 bowl to the floor'
            audio='Same bowl resonance; continuous kitchen ambience across cut'
            cut_motivation='Pet reaction begins after audible bowl placement'
            trust='CROSS_LOCATION_REFERENCE_NOT_APPROVED'
        },
        @{
            shot_id='C'; purpose='Visible response and story payoff'
            subject_id='MAOTAI-001'; setting_id='LIVINGROOM-PARTIAL-REAL'
            start_reference=$original; end_state='Maotai relaxed, cone and lime-green bandana unchanged'
            before_state='Same Maotai lying down, head near original angle'
            camera='Pet-eye-level medium portrait; same action side; stable focus'
            lighting='Warm source lighting, neutral grey wall'
            action='Maotai briefly looks toward the bowl sound and then toward owner'
            audio='Kitchen bowl sound precedes eyeline movement; quiet room tone follows'
            cut_motivation='Hold expression after the cause and response become clear'
            trust='REAL_FIRST_FRAME_ONLY; ACTION_GENERATED'
        }
    )
    foreach ($shot in $story) {
        foreach ($key in @('purpose','subject_id','setting_id','start_reference','before_state','end_state','camera','lighting','action','audio','cut_motivation')) {
            if ([string]::IsNullOrWhiteSpace([string]$shot[$key])) {
                throw ('STOP=DIRECTOR_CONTRACT_INCOMPLETE ' + $shot.shot_id + '/' + $key)
            }
        }
    }

    # 永久分镜      ：首次写入，后续不静默改动人工批准过的剧本。
    if (!(Test-Path -LiteralPath $contractFile -PathType Leaf)) {
        $story | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $contractFile -Encoding UTF8
    }

    # 资产事实与出处：生成图像不是实景证据；不能冒充用户真实厨房照片。
    $manifest = @{
        source_shots  = @('S02.mp4','S05.mp4')
        canonical_pet = @{ path=$original; sha256=$originSha; truth='REAL_PHOTO' }
        candidate_bowl = @{
            path=$bowlReference; sha256=(Get-FileHash $bowlReference -Algorithm SHA256).Hash.ToLowerInvariant()
            truth='SYNTHETIC_GENERATED_FRAME; CANONICAL_FOR_EXPERIMENT_ONLY'
        }
        rejected_alternative_bowl = @{
            path=$otherBowl; truth='DIFFERENT_BOWL; MUST_NOT_MIX_WITH_CANONICAL_CANDIDATE'
        }
        kitchen     = 'SYNTHETIC_NOT_OWNER_PHOTOGRAPHED'
        skill_rules = $skills
        stage       = 'INGREDIENTS_PILOT_REFERENCE_PREPARED_NOT_QUALITY_APPROVED'
        main_workflow = 'OFFICIAL LTX Desktop Ingredients IC-LoRA, not a custom diffusion executor'
    }
    $manifest | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath $reportFile -Encoding UTF8

    Write-Output 'PREPARE=PASS'
    Write-Output ('DIRECTOR_CONTRACT=' + $contractFile)
    Write-Output ('REFERENCE_BOARD=' + $storyboard)
    Write-Output 'REFERENCE_TRUST=REAL_MAOTAI_PLUS_SYNTHETIC_BOWL'
    Write-Output 'SKILL_SOURCES=VERIFIED; MODEL_AGENT_EXECUTION=NOT_CLAIMED'
    Write-Output 'NEW_GPU_POST=0'
}

function Get-SessionToken {
    # 本地认证      ：只从既有 DPAPI 文件解密，不读取或发送对话中的配对链接。
    if (!(Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
        throw 'STOP=REMOTE_SESSION_NOT_PAIRED'
    }
    $cipher = (Get-Content -LiteralPath $tokenFile -Raw -Encoding ASCII).Trim()
    $secret = ConvertTo-SecureString $cipher
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Api([string]$method,[string]$path,[object]$body=$null) {
    # 认证边界      ：仅本机配对 LTX API；不接触 Picotoo 正式 Core。
    $headers = @{ Authorization = ('Bearer ' + $script:ltxToken) }
    if ($method -eq 'GET') {
        return Invoke-RestMethod -Uri ($apiBase+$path) -Headers $headers -Method Get -TimeoutSec 20
    }
    $payload = ConvertTo-Json -InputObject $body -Depth 14 -Compress
    return Invoke-RestMethod -Uri ($apiBase+$path) -Headers $headers -Method Post -Body $payload -ContentType 'application/json' -TimeoutSec 90
}

function Get-IngredientsReadiness {
    # 真机模型核查  ：区分 Catalog 可见与专属 LTX2.5 权重已安装。
    $catalog = Api 'GET' '/api/ic-loras'
    $matches = @($catalog.ic_loras | Where-Object { $_.ic_lora.id -eq 'ingredients' })
    if ($matches.Count -ne 1) { throw 'STOP=INGREDIENTS_NOT_IN_LOCAL_CATALOG' }
    $ingredient = $matches[0]
    $versionReady = @($ingredient.downloaded_variant_ids) -contains 'ltx-2.5__ingredients'
    Write-Output ('INGREDIENTS_25_DOWNLOADED=' + $versionReady)
    if (!$versionReady) { Write-Output 'NEXT=LTX Desktop > Settings > Models > IC-LoRAs > Ingredients > LTX-2.5 Download' }

    $queue = Api 'GET' '/api/generation-queue'
    $busy = ($null -ne $queue.active) -or (@($queue.queued).Count -gt 0)
    Write-Output ('LTX_QUEUE_BUSY=' + $busy)

    return @{ modelReady=$versionReady; queueBusy=$busy }
}

function Upload-Image([string]$path) {
    # 图片接口      ：使用 .NET multipart；WinPS 5.1 没有 Invoke-RestMethod -Form。
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(90)
    $client.DefaultRequestHeaders.Authorization = New-Object Net.Http.Headers.AuthenticationHeaderValue('Bearer',$script:ltxToken)
    $stream = $null
    $form = $null
    try {
        $stream = [IO.File]::OpenRead($path)
        $part = New-Object Net.Http.StreamContent($stream)
        $part.Headers.ContentType = New-Object Net.Http.Headers.MediaTypeHeaderValue('image/jpeg')
        $form = New-Object Net.Http.MultipartFormDataContent
        $form.Add($part,'file',[IO.Path]::GetFileName($path))
        $resp = $client.PostAsync(($apiBase+'/api/assets/upload'),$form).GetAwaiter().GetResult()
        $raw = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (!$resp.IsSuccessStatusCode) { throw ('STOP=ASSET_UPLOAD_HTTP_'+[int]$resp.StatusCode) }
        $asset = ConvertFrom-Json -InputObject $raw
        if ($asset.media_kind -ne 'image' -or !$asset.id) { throw 'STOP=INVALID_UPLOADED_IMAGE' }
        return [string]$asset.id
    }
    finally {
        if ($null -ne $form) { $form.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
        $client.Dispose()
    }
}

# 只读准备与验证：Prepare 默认不启动视频，也不修改正式 HOLD。
if ($Mode -eq 'Prepare') {
    Prepare-Packet
    Start-Process explorer.exe -ArgumentList ('"' + $packageRoot + '"')
    return
}

$script:ltxToken = Get-SessionToken
$null = Api 'GET' '/api/session'

if ($Mode -eq 'Probe') {
    Prepare-Packet
    if (!(Test-Path -LiteralPath $settingsFile -PathType Leaf)) { throw 'STOP=LTX_SETTINGS_MISSING' }
    $settings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Output ('LOCAL_ENCODER=' + [bool]$settings.use_local_text_encoder)
    Write-Output ('VIDEO_API_SELECTED=' + [bool]$settings.user_prefers_ltx_api_video_generations)
    $null = Get-IngredientsReadiness
    Write-Output 'PROBE=PASS_READ_ONLY'
    return
}

if ($Mode -eq 'Status') {
    if (!(Test-Path -LiteralPath $receiptFile -PathType Leaf)) {
        if (Test-Path -LiteralPath $uncertainFile) { throw 'STOP=POST_UNCERTAIN_DO_NOT_RESUBMIT' }
        Write-Output 'PILOT=NOT_SUBMITTED'
        return
    }
    $receipt = Get-Content -LiteralPath $receiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $id = [string]$receipt.generation_id
    $generation = Api 'GET' ('/api/generations/'+[Uri]::EscapeDataString($id))
    Write-Output ('PILOT_GENERATION_ID='+$id)
    Write-Output ('PILOT_STATUS='+$generation.status)
    if ($generation.status -eq 'succeeded' -and !(Test-Path -LiteralPath $outputFile -PathType Leaf)) {
        $videos = @($generation.outputs | Where-Object { $_.media_kind -eq 'video' })
        if ($videos.Count -ne 1) { throw 'STOP=OUTPUT_ASSET_AMBIGUOUS' }
        $signed = [string]$videos[0].bytes_url
        if ($signed -notmatch '^/api/assets/[a-f0-9-]+/bytes\?') { throw 'STOP=UNTRUSTED_SIGNED_MEDIA_URL' }
        $temp = $outputFile + '.partial'
        if (Test-Path -LiteralPath $temp) { throw 'STOP=UNFINISHED_EXPORT_TEMP_EXISTS' }
        $headers = @{ Authorization = ('Bearer '+$script:ltxToken) }
        Invoke-WebRequest -Uri ($apiBase+$signed) -OutFile $temp -Headers $headers -UseBasicParsing -TimeoutSec 300
        if (!(Test-Path $temp -PathType Leaf) -or (Get-Item $temp).Length -lt 4096) { throw 'STOP=EXPORT_EMPTY' }
        Move-Item -LiteralPath $temp -Destination $outputFile
    }
    if (Test-Path -LiteralPath $outputFile -PathType Leaf) {
        Write-Output ('OUTPUT_FILE='+$outputFile)
        Write-Output ('OUTPUT_SHA256='+(Get-FileHash $outputFile -Algorithm SHA256).Hash.ToLowerInvariant())
        Write-Output 'HUMAN_VISUAL_ACCEPT=PENDING'
    }
    Write-Output 'NEW_GPU_POST=0'
    return
}

if ($Mode -eq 'Pilot') {
    Prepare-Packet
    if (Test-Path -LiteralPath $receiptFile) { throw 'STOP=PILOT_ALREADY_SUBMITTED_CHECK_STATUS' }
    if (Test-Path -LiteralPath $uncertainFile) { throw 'STOP=POST_UNCERTAIN_DO_NOT_RESUBMIT' }
    if (!(Test-Path -LiteralPath $settingsFile -PathType Leaf)) { throw 'STOP=LTX_SETTINGS_MISSING' }
    $settings = Get-Content -LiteralPath $settingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($settings.use_local_text_encoder -ne $true -or $settings.user_prefers_ltx_api_video_generations -eq $true) {
        throw 'STOP=LOCAL_ENCODER_OR_VIDEO_MODE_NOT_CONFIRMED'
    }
    $ready = Get-IngredientsReadiness
    if (!$ready.modelReady) { throw 'STOP=DOWNLOAD_LTX25_INGREDIENTS_FIRST' }
    if ($ready.queueBusy) { throw 'STOP=LTX_QUEUE_BUSY' }

    # 单镜头试验    ：把已验证茅台和一套虚构食盆同时作为 Ingredients 参考。
    $prompt = 'Reference sheet: Panel 1 shows the real Maotai, an adult Alaskan Malamute with distinctive pink-and-black mottled nose, cream eyebrows, cream-edged ears, black/deep-brown/tan/cream fur, wearing a translucent recovery cone and lime-green bandana, lying on light wooden floor in warm indoor light with a grey wall and white doorway. Panel 2 shows ONE specific brushed stainless-steel dog bowl containing small brown dry kibble, photographed in a warm neutral home kitchen; preserve this exact bowl shape and metal finish. Generated video: In the same warm home interior, a hand carefully sets that exact bowl on the same pale wooden floor near Maotai, with a quiet authentic metallic bowl contact sound. Maotai stays in the same lying pose, notices the bowl with a small natural eye movement, and looks expectantly toward the off-screen owner. One continuous stable low dog-eye-level shot, consistent dog nose, ears, coat, collar, cone, bowl, lighting direction, shadows and room geometry; no duplicate bowl, no new dog, no extra limbs, no aggressive morphing, no captions or logos. Subtle realistic room ambience and metal contact audio.'

    # 上传可重复素材：只有两张源图，后续生成保留任务身份和原始 SHA。
    $petAsset  = Upload-Image $original
    $bowlAsset = Upload-Image $bowlReference
    $request = @{
        contract_version = 1
        inputs = @{ images = @(@{assetId=$petAsset},@{assetId=$bowlAsset}) }
        params = @{
            prompt = $prompt
            promptProvenance = 'enhanced'
            model = 'ltx-2.5-fast'
            resolution = '540p'
            aspectRatio = '9:16'
            duration = 5
            fps = 24
            audioMode = 'generated'
            scale = 1.4
            variantId = 'ltx-2.5__ingredients'
        }
    }

    # 提交锁        ：任何响应未知的 POST 都绝不自动重试。
    [IO.File]::WriteAllText($uncertainFile, ('REQUEST_BEGAN_UTC='+[DateTime]::UtcNow.ToString('o')))
    try {
        $g = Api 'POST' '/api/generations/ic-lora-recipes/ingredients' $request
        if (!$g.id) { throw 'RESPONSE_MISSING_GENERATION_ID' }
        @{
            generation_id = [string]$g.id
            submitted_utc = [DateTime]::UtcNow.ToString('o')
            model = 'ltx-2.5-fast'
            recipe = 'ingredients'
            variant = 'ltx-2.5__ingredients'
            source_photo_sha = $originSha
            source_bowl_sha = (Get-FileHash $bowlReference -Algorithm SHA256).Hash.ToLowerInvariant()
            approval = 'EXPERIMENTAL_SYNTHETIC_BOWL_NOT_REAL_KITCHEN'
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptFile -Encoding UTF8
        Remove-Item -LiteralPath $uncertainFile -Force
        Write-Output 'PILOT_SUBMISSION=PASS'
        Write-Output ('GENERATION_ID='+[string]$g.id)
        Write-Output 'NEW_GPU_POST=1'
        Write-Output 'FORMAL_PICOTOO_WORKER_HOLD=UNCHANGED'
        Write-Output 'NEXT=Run -Mode Status after LTX finishes'
    }
    catch {
        throw ('STOP=SUBMISSION_UNKNOWN_DO_NOT_REPEAT '+$_.Exception.Message)
    }
}