[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$RepositoryRoot,
 [Parameter(Mandatory)][string]$ScenarioIndex,
 [Parameter(Mandatory)][string]$OutputDirectory,
 [string]$C011StageRoot='',
 [string]$C011CommitSha='',
 [string]$C011TestProject=''
)
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
Set-StrictMode -Version Latest
$repo=(Resolve-Path -LiteralPath $RepositoryRoot).Path
$index=Get-Content -LiteralPath $ScenarioIndex -Raw | ConvertFrom-Json
$ids=@($index.scenario_groups | ForEach-Object {$_.ids} | ForEach-Object {$_})
$expected=@(1..36|ForEach-Object {'FV-{0:D3}' -f $_})
if($index.schema_version -ne '1.0' -or $ids.Count -ne 36 -or @($ids|Sort-Object -Unique).Count -ne 36){throw 'FV_INDEX_INVALID'}
foreach($id in $expected){if(@($ids|Where-Object {$_ -eq $id}).Count -ne 1){throw "FV_INDEX_MISSING_$id"}}
New-Item -ItemType Directory -Force -Path $OutputDirectory|Out-Null
$source=(& git -C $repo rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0 -or $source -notmatch '^[a-f0-9]{40}$'){throw 'FV_SOURCE_COMMIT_INVALID'}
$requiredSdk=(Get-Content (Join-Path $repo 'windows/desktop/global.json') -Raw|ConvertFrom-Json).sdk.version
Push-Location (Join-Path $repo 'windows/desktop')
try { $actualSdk=(& dotnet --version).Trim() } finally { Pop-Location }
if($LASTEXITCODE -ne 0 -or $actualSdk -ne $requiredSdk){throw "FV_SDK_MISMATCH expected=$requiredSdk actual=$actualSdk"}
$cases=[ordered]@{}
foreach($id in $expected){
 $manual=$id -in @('FV-032','FV-033','FV-034')
 $cases[$id]=[ordered]@{
  id=$id;status=$(if($manual){'UNVERIFIED'}else{'BLOCKED'})
  blocker=$(if($manual){'PUBLISHED_WINDOWS_EVIDENCE_REQUIRED'}else{'BLOCKED_C011'})
  scope='FULL_QA_GATED_E2E';component_evidence=@()
 }
}
$suites=[ordered]@{}
$problem=$null
function Save-Report {
 $counts=[ordered]@{
  total=36;pass=@($cases.Values|Where-Object {$_.status -eq 'PASS'}).Count
  fail=@($cases.Values|Where-Object {$_.status -eq 'FAIL'}).Count
  blocked=@($cases.Values|Where-Object {$_.status -eq 'BLOCKED'}).Count
  unverified=@($cases.Values|Where-Object {$_.status -eq 'UNVERIFIED'}).Count
  qa_gated_e2e_pass=@($cases.Values|Where-Object {$_.status -eq 'PASS' -and $_.scope -eq 'FULL_QA_GATED_E2E'}).Count
 }
 $report=[ordered]@{
  schema_version='1.0';source_sha=$source;c011_sha=$(if($C011CommitSha){$C011CommitSha}else{$null})
  os=[Environment]::OSVersion.VersionString;dotnet_sdk=$actualSdk
  created_utc=[DateTimeOffset]::UtcNow.ToString('o')
  counts=$counts;components=$suites;cases=@($cases.Values);error=$problem
 }
 $result=Join-Path $OutputDirectory 'final-video-e2e-results.json'
 $report|ConvertTo-Json -Depth 16|Set-Content -LiteralPath $result -Encoding utf8
 Write-Host "FV_E2E_RESULT PASS=$($counts.pass) FAIL=$($counts.fail) BLOCKED=$($counts.blocked) UNVERIFIED=$($counts.unverified)"
 Write-Host "FV_E2E_QA_GATED_PASS=$($counts.qa_gated_e2e_pass)"
 Write-Host "FV_E2E_REPORT=$result"
}
function Run-RealSuite([string]$name,[string]$root,[string]$project,[string[]]$markers){
 $full=Join-Path $root $project
 if(-not (Test-Path -LiteralPath $full -PathType Leaf)){throw "FV_PROJECT_MISSING=$project"}
 $log=Join-Path $OutputDirectory "$name.log"
 $temporaryUsing=$null
 if($name -in @('C009A','C009B')){
  # Temporary test-only source in the CI checkout; never commit or modify upstream assertions.
  $temporaryUsing=Join-Path (Split-Path $full -Parent) '__E2E_TEMP_USINGS.g.cs'
  if(Test-Path -LiteralPath $temporaryUsing){throw 'FV_TEMP_USINGS_ALREADY_EXISTS'}
  @(
   'global using System;','global using System.IO;','global using System.Linq;',
   'global using System.Collections.Generic;','global using System.Threading;',
   'global using System.Threading.Tasks;','global using System.Diagnostics;',
   'global using System.Text;','global using System.Security.Cryptography;'
  )|Set-Content -LiteralPath $temporaryUsing -Encoding utf8
 }
 Push-Location (Join-Path $root 'windows/desktop')
 try{
  & dotnet build $full -c Release --nologo --warnaserror *> $log
  if($LASTEXITCODE -ne 0){throw "FV_BUILD_FAILED=$name"}
  & dotnet run --no-build --project $full -c Release --no-launch-profile *>> $log
  if($LASTEXITCODE -ne 0){throw "FV_TEST_FAILED=$name"}
  $raw=Get-Content -LiteralPath $log -Raw
  foreach($marker in $markers){if(-not $raw.Contains($marker)){throw "FV_MARKER_MISSING=$name $marker"}}
  if($raw.Contains('=UNVERIFIED') -or $raw.Contains('=FAIL')){throw "FV_UNVERIFIED_OR_FAIL=$name"}
  $suites[$name]=[ordered]@{status='PASS';sha=(& git -C $root rev-parse HEAD).Trim();log="$name.log";markers=$markers}
  Write-Host "FV_REAL_SUITE_$name=PASS"
  return $raw
 }finally{
  Pop-Location
  if($temporaryUsing -and (Test-Path -LiteralPath $temporaryUsing)){
   Remove-Item -LiteralPath $temporaryUsing -Force
  }
 }
}
function Add-Evidence([string[]]$matching,[string]$name,[string]$detail){
 foreach($id in $matching){
  $cases[$id].component_evidence=@($cases[$id].component_evidence)+@([ordered]@{
   suite=$name;result='PASS';scope='COMPONENT_ONLY_NOT_E2E';detail=$detail
  })
 }
}
try {
 if(-not [OperatingSystem]::IsWindows()){throw 'FV_WINDOWS_REQUIRED'}
 $null=Run-RealSuite 'C009A' $repo 'windows/desktop/tests/PicotooPet.PostProductionMaster.SmokeTests/PicotooPet.PostProductionMaster.SmokeTests.csproj' @(
  'PASS first compose and exact restart','PASS lineage fails before output root',
  'PASS tampered upstream bytes fail closed','PASS partial and tampered masters conflict',
  'PASS stale wrong digest is never selected','PASS no postproduction returns C004 fallback',
  'POSTPRODUCTION_MASTER_SMOKE=PASS'
 )
 Add-Evidence @('FV-001','FV-002','FV-012','FV-015','FV-016','FV-017','FV-019','FV-021','FV-022') 'C009A' 'Immutable master tests only, not QA'
 $null=Run-RealSuite 'C009B' $repo 'windows/desktop/tests/PicotooPet.PostProductionMasterMux.SmokeTests/PicotooPet.PostProductionMasterMux.SmokeTests.csproj' @(
  'MASTER_MUX_UNIT=PASS','MASTER_MUX_REAL_LANDSCAPE=PASS','MASTER_MUX_REAL_VERTICAL=PASS',
  'MASTER_MUX_REAL_SQUARE=PASS','MASTER_MUX_REAL_ZERO_NARRATION=PASS',
  'MASTER_MUX_REAL_BOUNDED_AND_FAILURE=PASS','MASTER_MUX_REAL_WINDOWS=PASS'
 )
 Add-Evidence @('FV-003','FV-004','FV-005','FV-010','FV-028','FV-030','FV-031','FV-035') 'C009B' 'Real Windows FFmpeg packet MD5/audio, not QA'
 $cases['FV-030'].status='PASS'
 $cases['FV-030'].blocker=$null
 $cases['FV-030'].scope='NATIVE_WINDOWS_MEDIA_PROFILE_ONLY'
 if($C011CommitSha -or $C011StageRoot -or $C011TestProject){
  if($C011CommitSha -notmatch '^[0-9a-f]{40}$' -or -not $C011StageRoot -or -not $C011TestProject){throw 'FV_C011_PIN_AND_TEST_REQUIRED'}
  $stage=(Resolve-Path -LiteralPath $C011StageRoot).Path
  $head=(& git -C $stage rev-parse HEAD).Trim()
  if($LASTEXITCODE -ne 0 -or $head -cne $C011CommitSha){throw "FV_C011_PIN_MISMATCH expected=$C011CommitSha actual=$head"}
  if($head -eq '9b95b722ba9a5058e1fbfa10cf7d56baff43d64c'){throw 'BLOCKED_C011_NO_INTEGRATION'}
  $project=$C011TestProject.Replace('/','\')
  if([IO.Path]::IsPathRooted($project) -or $project.Contains('..') -or
   -not $project.StartsWith('windows\desktop\tests\',[StringComparison]::OrdinalIgnoreCase) -or
   -not $project.EndsWith('.csproj',[StringComparison]::OrdinalIgnoreCase)){throw 'FV_C011_PROJECT_UNTRUSTED'}
  $stageSdk=(Get-Content (Join-Path $stage 'windows/desktop/global.json') -Raw|ConvertFrom-Json).sdk.version
  if($stageSdk -ne $requiredSdk){throw 'FV_C011_SDK_MISMATCH'}
  $stageOut=Run-RealSuite 'C011' $stage $project @('FINAL_VIDEO_QA_GATED_INTEGRATION=PASS')
  foreach($id in $expected){
   if($id -in @('FV-032','FV-033','FV-034')){continue}
   if($stageOut -match "(?m)^$([regex]::Escape($id))=PASS\s*$"){
    $cases[$id].status='PASS';$cases[$id].blocker=$null;$cases[$id].scope='FULL_QA_GATED_E2E'
   }
  }
 }
}catch{
 $problem=$_.Exception.Message
 Write-Host "FV_E2E_DRIVER_ERROR=$problem"
}finally{Save-Report}
if($problem){exit 1}
Write-Host 'FV_E2E_DRIVER=PASS_WITH_C011_BLOCKED_CASES'
exit 0
