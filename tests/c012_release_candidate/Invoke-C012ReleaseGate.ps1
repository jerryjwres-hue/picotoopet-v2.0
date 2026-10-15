[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$CandidateRoot,
 [Parameter(Mandatory)][string]$EvidenceDirectory,
 [Parameter(Mandatory)][string]$ExpectedCandidateCommit
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
if(-not [OperatingSystem]::IsWindows()){throw 'C012_RELEASE_GATE_WINDOWS_REQUIRED'}
$repo=(Resolve-Path -LiteralPath $CandidateRoot).Path
$evidence=[IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $evidence|Out-Null
$head=(& git -C $repo rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0 -or $head -cne $ExpectedCandidateCommit){throw 'C012_RELEASE_CHECKOUT_MISMATCH'}
$builder=Join-Path $repo 'windows/desktop/scripts/Build-Phase2WindowsRelease.ps1'
if(-not(Test-Path -LiteralPath $builder)){throw 'C012_OFFICIAL_RELEASE_BUILDER_MISSING'}
$log=Join-Path $evidence 'c012-full-release.log'
$output=Join-Path $evidence 'official-full-release-work'
$complete=$false;$exception=$null
try{
 & $builder -OutputRoot $output -ValidationScope Full -Version ('c012-validation-'+$head.Substring(0,12)) *> $log
 $complete=$true
}catch{
 $exception=$_.Exception.GetType().Name+':'+$_.Exception.Message
 Add-Content -LiteralPath $log -Value ('C012_RELEASE_BUILDER_ERROR='+$exception)
}
$raw=if(Test-Path -LiteralPath $log){Get-Content -LiteralPath $log -Raw}else{''}
$known=$raw.Contains('PHASE2_CORE_SMOKE=FAIL') -and $raw.Contains('torso_neutral.png')
$zips=@(Get-ChildItem -LiteralPath $output -Filter '*.zip' -File -ErrorAction SilentlyContinue)
if($known -and (-not $complete) -and $zips.Count -eq 0){
 $status='BLOCKED';$reason='ISSUE_78_MAOTAI_TORSO_NEUTRAL_PNG_REAL_FULL_RELEASE_SMOKE'
}elseif(-not $complete){
 $status='FAIL';$reason='UNEXPECTED_NATIVE_FULL_RELEASE_BUILDER_ERROR'
}else{
 # C012 custom workflow is NOT an officially whitelisted release provenance.
 $status='BLOCKED';$reason='OFFICIAL_WHITELISTED_RELEASE_ATTESTATION_AND_INSTALL_VALIDATION_REQUIRED'
}
$gate=[ordered]@{
 status=$status;reason=$reason;builder_completed=$complete
 native_full_builder_invoked=$true;validation_scope='Full'
 issue78_missing_asset_verified=$known
 zip_count=$zips.Count;source_head=$head
 log='c012-full-release.log'
 log_sha256=$(if(Test-Path -LiteralPath $log){(Get-FileHash -LiteralPath $log -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null})
 exception_type_and_message=$exception
}
$gate | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $evidence 'c012-release-gate.json') -Encoding utf8
$testsPath=Join-Path $evidence 'c012-candidate-tests.json'
$tests=if(Test-Path -LiteralPath $testsPath){Get-Content -LiteralPath $testsPath -Raw|ConvertFrom-Json}else{$null}
$gateSuite=[ordered]@{}
foreach($name in @('C009B','C010A','C010B','C011','G005')){
 $gateSuite[$name]=if($null -ne $tests -and $null -ne $tests.suites.$name){
  $tests.suites.$name.status
 }else{'BLOCKED'}
}
$readiness=[ordered]@{
 schema_version='picotoopet.c012.release-readiness.v1'
 generated_utc=[DateTimeOffset]::UtcNow.ToString('o')
 candidate_head=$head
 frozen_base_sha='ec468b9975a3b1cd706e6e74223bfb05f7733a86'
 c009b_pr74_sha='1e75cab7daf201a1883e3e98ea5ddb8a753e8e82'
 c010b_tests_sha='8c8f1d7c01dc82baf2df636ef93df5af7125cd3c'
 g005_tests_sha='99cccbb867c3c4d532e816907f2350a0c6d043e0'
 native_windows_actions_run_id=$env:GITHUB_RUN_ID
 native_windows_actions_run_attempt=$env:GITHUB_RUN_ATTEMPT
 candidate_production_binary_provenance='C012 HEAD source compiled by native Windows dotnet Release, not old owner branch binaries'
 regression_gates=$gateSuite
 native_regression_report='c012-candidate-tests.json'
 formal_release_gate=$gate
 e2e_residuals=[ordered]@{
 'FV-012'='BLOCKED_REAL_ATOMIC_PROCESS_CRASH_NOT_PROVEN'
 'FV-031'='BLOCKED_REAL_AAC_TIMELINE_CORRUPTION_NOT_PROVEN'
 'FV-035'='BLOCKED_REAL_MISSING_FFMPEG_PATH_NOT_PROVEN'
 'FV-032'='UNVERIFIED_PUBLISHED_GUI_CONCURRENT_OPEN'
 'FV-033'='BLOCKED_RELEASE_ASSET_AND_UNVERIFIED_CLEAN_INSTALL'
 'FV-034'='UNVERIFIED_REAL_PUBLISHED_PID_KILL_AND_RESTART'
 }
 live_mac_core='UNVERIFIED_REAL_HTTP_NETWORK_TRANSPORT_RECONNECT'
 issue83_unfrozen_source_absorbed=$false
 c011_qa_goal_center_source_changed=$false
 published_installer_available_for_release=$false
 release_ready=$false
}
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $evidence 'c012-release-readiness.json') -Encoding utf8
Write-Host "C012_RELEASE_GATE=$status reason=$reason"
Write-Host "C012_RELEASE_BUILDER_TORSO_BLOCK_OBSERVED=$known"
Write-Host "C012_RELEASE_READY=NO"
Write-Host "C012_RELEASE_READINESS_MANIFEST=$(Join-Path $evidence 'c012-release-readiness.json')"
if($status -eq 'FAIL'){exit 1}
exit 0
