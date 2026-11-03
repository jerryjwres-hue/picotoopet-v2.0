# Independent synthetic compatibility test; no product or user-data changes.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Root)
$ErrorActionPreference = 'Stop'
function Require([bool]$Value, [string]$Reason) { if (-not $Value) { throw $Reason } }
function Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function PngSize([string]$Path) {
    $b = [IO.File]::ReadAllBytes($Path)
    Require ($b.Length -gt 24 -and [Convert]::ToHexString($b[0..7]) -eq '89504E470D0A1A0A') 'PNG_SIGNATURE'
    $w = [byte[]]$b[16..19]; [Array]::Reverse($w)
    $h = [byte[]]$b[20..23]; [Array]::Reverse($h)
    @([BitConverter]::ToUInt32($w,0), [BitConverter]::ToUInt32($h,0))
}
$ffmpeg = "$Root/ffmpeg/ffmpeg.exe"
$ffprobe = "$Root/ffmpeg/ffprobe.exe"
$fixture = Get-Content "$PSScriptRoot/fixtures.json" -Raw | ConvertFrom-Json
$evidence = "$Root/evidence"
$config = Get-Content "$Root/ffmpeg/config.h" -Raw
foreach ($key in 'CONFIG_GPL','CONFIG_NONFREE','CONFIG_NETWORK') {
    Require ($config -match "(?m)^#define $key 0\s*$") "FORBIDDEN_BUILD_FEATURE_$key"
}
Require ($config -match '(?m)^#define CONFIG_ZLIB 1\s*$') 'ZLIB_MISSING'
$versions = Get-Content "$evidence/ffmpeg-version.txt" -Raw
Require ($versions -notmatch '--enable-gpl|--enable-nonfree') 'FORBIDDEN_CONFIGURE'
& $ffmpeg -L 2>&1 | Set-Content "$evidence/actual-license.txt"
Require ($LASTEXITCODE -eq 0) 'LICENSE_COMMAND_FAILED'
Require ((Get-Content "$evidence/actual-license.txt" -Raw) -match 'Lesser General Public License') 'NOT_LGPL'
& dotnet build tools/p0_visual_review/PicotooPet.VisualReview.csproj -c Release --warnaserror
if ($LASTEXITCODE) { throw 'UNCHANGED_OBSERVER_BUILD_FAILED' }
$observer = (Resolve-Path 'tools/p0_visual_review/bin/Release/net10.0/PicotooPet.VisualReview.dll').Path
$results = @()
foreach ($codec in 'vp8','vp9') {
    $media = "$Root/media-$codec"
    New-Item -ItemType Directory $media | Out-Null
    $shots = @()
    foreach ($f in @($fixture.fixtures | Where-Object codec -eq $codec)) {
        $p = "$media/$($f.name)"
        [IO.File]::WriteAllBytes($p, [Convert]::FromBase64String($f.base64))
        Require ((Sha $p) -ceq $f.sha256 -and (Get-Item $p).Length -eq $f.bytes) 'FIXTURE_PIN_MISMATCH'
        $shots += [ordered]@{
            order=$f.order; shot_id="shot$($f.order)"; task_id="task$($f.order)"
            relative_path=$f.name; sha256=$f.sha256; bytes=$f.bytes
            expected_frames=$f.expected_frames; expected_duration_ms=$f.expected_duration_ms
            action="Independent solid-color $codec fixture, not real pet media"
        }
    }
    Require ($shots.Count -eq 3) 'FIXTURE_COUNT'
    $manifestPath = "$Root/input-$codec.json"
    @{schema_version='visual_review.input.v1'; job_id='19500000-0000-4000-8000-000000000001'; shots=$shots} |
        ConvertTo-Json -Depth 8 | Set-Content $manifestPath -Encoding utf8
    $output = "$evidence/$codec"
    & dotnet $observer $manifestPath $media $output $ffprobe $ffmpeg
    Require ($LASTEXITCODE -eq 0) "ACTUAL_OBSERVER_FAILED_$codec"
    $r = Get-Content "$output/report.json" -Raw | ConvertFrom-Json
    Require ($r.schema_version -ceq 'visual_review.v1' -and $r.status -ceq 'ADVISORY_REVIEW' -and
        $r.model_state -ceq 'NOT_REQUESTED' -and $r.shots.Count -eq 3) 'REPORT_CONTRACT'
    Require (@(Get-ChildItem "$output/frames" -Filter '*.png').Count -eq 9) 'NINE_FRAMES_REQUIRED'
    $sheet = "$output/contact_sheet_3x3.png"
    Require ((Sha $sheet) -ceq $r.contact_sheet_sha256) 'CONTACT_SHEET_HASH'
    $size = PngSize $sheet
    Require ($size[0] -eq 976 -and $size[1] -eq 556) 'CONTACT_SHEET_3X3_DIMENSIONS'
    foreach ($s in $r.shots) {
        $original = $shots[$s.order-1]
        Require ($s.frames -eq 96 -and [Math]::Abs($s.duration_ms-4000) -le 250 -and
            $s.source_sha256 -ceq $original.sha256 -and (Sha "$media/$($original.relative_path)") -ceq $original.sha256) 'SOURCE_FACTS'
        Require ($s.samples.Count -eq 3) 'THREE_SAMPLES_PER_SHOT'
        foreach ($sample in $s.samples) {
            $p = "$output/frames/$($sample.filename)"
            Require ((Sha $p) -ceq $sample.sha256 -and (Get-Item $p).Length -eq $sample.bytes) 'FRAME_HASH_OR_LENGTH'
            Require ($sample.shot_id -ceq $s.shot_id -and $sample.task_id -ceq $s.task_id -and
                $sample.grid_index -ge (($s.order-1)*3) -and $sample.grid_index -lt ($s.order*3)) 'FRAME_IDENTITY'
            Require (@(1000,2000,3000) -contains [int]$sample.timecode_ms) 'FRAME_TIMESTAMP'
            $size = PngSize $p
            Require ($size[0] -eq 320 -and $size[1] -eq 180) 'FRAME_DIMENSIONS'
        }
    }
    # Mutate actual source bytes at fixed length; keep the ORIGINAL manifest digest.
    $first = "$media/$($shots[0].relative_path)"
    $b = [IO.File]::ReadAllBytes($first); $b[$b.Length-1] = $b[$b.Length-1] -bxor 1
    [IO.File]::WriteAllBytes($first,$b)
    Require ((Get-Item $first).Length -eq $shots[0].bytes -and (Sha $first) -cne $shots[0].sha256) 'TAMPER_FIXTURE_NOT_CHANGED'
    $negative = "$evidence/$codec-tamper"
    & dotnet $observer $manifestPath $media $negative $ffprobe $ffmpeg
    Require ($LASTEXITCODE -eq 2) 'SOURCE_TAMPER_EXIT'
    $n = Get-Content "$negative/report.json" -Raw | ConvertFrom-Json
    Require ($n.status -ceq 'UNVERIFIED') 'TAMPER_MUST_BE_UNVERIFIED'
    $results += @{codec=$codec; synthetic_compatibility='PASS'; source_tamper='UNVERIFIED'; contact_sheet_sha256=$r.contact_sheet_sha256}
}
$binaries = foreach ($p in $ffmpeg,$ffprobe) { @{name=(Split-Path $p -Leaf); bytes=(Get-Item $p).Length; sha256=(Sha $p)} }
$maps = @()
foreach ($n in 'ffmpeg','ffprobe') {
    $path = "$evidence/$n.map"
    Require (Test-Path $path) 'LINK_MAP_MISSING'
    $text = Get-Content $path -Raw
    $archives = @([regex]::Matches($text,'[^\s()]+\.a(?=\(|\s|$)') | ForEach-Object Value | Sort-Object -Unique)
    # Full link maps/imports/configs are authoritative evidence; no claim that this regex is legal closure.
    $maps += @{executable=$n; archive_tokens=$archives; inventory_status='REQUIRES_INDEPENDENT_SOURCE_AND_RUNTIME_REVIEW'}
}
@{source_sha=(git rev-parse HEAD); technical_status='PASS'; compliance='BLOCKED'; user_install_allowed=$false
  tests=$results; candidate_binaries=$binaries; link_maps=$maps; explicit_third_party_library='zlib'
  runtime_and_per_file_license_closure='UNVERIFIED'; gpu=0; models=0; comfy_posts=0
  observer_source_sha256=(Sha 'tools/p0_visual_review/Program.cs')} |
    ConvertTo-Json -Depth 10 | Set-Content "$evidence/status.json"
$global:LASTEXITCODE = 0
