[CmdletBinding()]
param([Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $root | Out-Null
if(-not $root.Contains('final-video-e2e',[StringComparison]::OrdinalIgnoreCase)){
 throw 'FV_FIXTURE_ROOT_MUST_BE_DISPOSABLE'
}
function Hash([string]$path){return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
$fixtures=[ordered]@{}
$baseline=Join-Path $root 'baseline'
New-Item -ItemType Directory -Force -Path $baseline|Out-Null
$video=Join-Path $baseline 'master.mp4'
$manifest=Join-Path $baseline 'master-manifest.json'
$receipt=Join-Path $baseline 'receipt.json'
# Deliberately NOT real production files or valid C010 receipts. Inputs are disposable
# adversarial bytes for future C011 adapter; never promote them as QA-verified artifacts.
[IO.File]::WriteAllBytes($video,[Text.Encoding]::UTF8.GetBytes('UNTRUSTED_E2E_FIXTURE_MEDIA_01'))
[IO.File]::WriteAllText($manifest,'{"test_fixture_only":true,"identity":"alpha"}')
[IO.File]::WriteAllText($receipt,'{"test_fixture_only":true,"status":"FAKE_PASS_NOT_AUTHORIZED"}')
$baselineHash=Hash $video
$manifestHash=Hash $manifest
$receiptHash=Hash $receipt
$fixtures['baseline']=[ordered]@{
 video=$video;manifest=$manifest;receipt=$receipt
 video_sha256=$baselineHash;manifest_sha256=$manifestHash
 receipt_sha256=$receiptHash;authority='NONE_FIXTURE_ONLY'
}
function Make-Mutation([string]$id,[scriptblock]$mutator){
 $dir=Join-Path $root $id
 New-Item -ItemType Directory -Force -Path $dir|Out-Null
 foreach($name in @('master.mp4','master-manifest.json','receipt.json')){
  Copy-Item -LiteralPath (Join-Path $baseline $name) -Destination (Join-Path $dir $name)
 }
 & $mutator $dir
 $movie=Join-Path $dir 'master.mp4'
 $man=Join-Path $dir 'master-manifest.json'
 $rec=Join-Path $dir 'receipt.json'
 $fixtures[$id]=[ordered]@{
  directory=$dir;video_exists=(Test-Path -LiteralPath $movie -PathType Leaf)
  manifest_exists=(Test-Path -LiteralPath $man -PathType Leaf)
  receipt_exists=(Test-Path -LiteralPath $rec -PathType Leaf)
  video_sha256=$(if(Test-Path -LiteralPath $movie -PathType Leaf){Hash $movie}else{$null})
  manifest_sha256=$(if(Test-Path -LiteralPath $man -PathType Leaf){Hash $man}else{$null})
  receipt_sha256=$(if(Test-Path -LiteralPath $rec -PathType Leaf){Hash $rec}else{$null})
  authority='NONE_FIXTURE_ONLY'
 }
}
Make-Mutation 'FV-018-video-byte-tamper' {param($d)
 $p=Join-Path $d 'master.mp4';$b=[IO.File]::ReadAllBytes($p);$b[4]=$b[4] -bxor 1;[IO.File]::WriteAllBytes($p,$b)
}
Make-Mutation 'FV-019-manifest-byte-tamper' {param($d)
 $p=Join-Path $d 'master-manifest.json';[IO.File]::AppendAllText($p,' ')
}
Make-Mutation 'FV-020-receipt-tamper' {param($d)
 $p=Join-Path $d 'receipt.json';[IO.File]::AppendAllText($p,' ')
}
Make-Mutation 'FV-025-click-substitution' {param($d)
 $p=Join-Path $d 'master.mp4';[IO.File]::WriteAllText($p,'OTHER_MOVIE_DIFFERENT_CONTENT')
}
Make-Mutation 'FV-026-removed-managed-output' {param($d)
 Remove-Item -LiteralPath (Join-Path $d 'master.mp4')
}
Make-Mutation 'FV-027-same-video-foreign-manifest' {param($d)
 [IO.File]::WriteAllText((Join-Path $d 'master-manifest.json'),'{"test_fixture_only":true,"identity":"other"}')
}
Make-Mutation 'FV-029-truncated-video' {param($d)
 $p=Join-Path $d 'master.mp4';$b=[IO.File]::ReadAllBytes($p);[IO.File]::WriteAllBytes($p,$b[0..7])
}
Make-Mutation 'FV-036-untrusted-receipt' {param($d)
 [IO.File]::WriteAllText((Join-Path $d 'receipt.json'),'{"test_fixture_only":true,"status":"FAKE_PASS_FROM_OTHER_JOB"}')
}
if($fixtures['FV-018-video-byte-tamper'].video_sha256 -eq $baselineHash){throw 'FV_FIXTURE_VIDEO_MUTATION_NOOP'}
if($fixtures['FV-019-manifest-byte-tamper'].manifest_sha256 -eq $manifestHash){throw 'FV_FIXTURE_MANIFEST_MUTATION_NOOP'}
if($fixtures['FV-020-receipt-tamper'].receipt_sha256 -eq $receiptHash){throw 'FV_FIXTURE_RECEIPT_MUTATION_NOOP'}
if($fixtures['FV-025-click-substitution'].video_sha256 -eq $baselineHash){throw 'FV_FIXTURE_SUBSTITUTION_NOOP'}
if($fixtures['FV-027-same-video-foreign-manifest'].video_sha256 -ne $baselineHash){throw 'FV_FIXTURE_SAME_VIDEO_ALTERED'}
if($fixtures['FV-027-same-video-foreign-manifest'].manifest_sha256 -eq $manifestHash){throw 'FV_FIXTURE_FOREIGN_MANIFEST_NOOP'}
if($fixtures['FV-026-removed-managed-output'].video_exists){throw 'FV_FIXTURE_REMOVED_FILE_PRESENT'}
$path=Join-Path $root 'fixture-evidence.json'
([ordered]@{
 schema_version='1.0'
 created_utc=[DateTimeOffset]::UtcNow.ToString('o')
 non_authoritative=$true
 kind='DISPOSABLE_NEGATIVE_INPUTS_NOT_PRODUCTION_ARTIFACTS'
 fixtures=$fixtures
})|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $path -Encoding utf8
Write-Host 'FV_DISPOSABLE_FIXTURE_MUTATIONS=PASS'
Write-Host "FV_DISPOSABLE_FIXTURE_REPORT=$path"
