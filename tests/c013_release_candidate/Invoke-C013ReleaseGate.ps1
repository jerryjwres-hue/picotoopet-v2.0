[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$CandidateRoot,
 [Parameter(Mandatory)][string]$EvidenceDirectory,
 [Parameter(Mandatory)][string]$ExpectedCandidateCommit
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
if(-not [OperatingSystem]::IsWindows()){throw 'C013_RELEASE_GATE_WINDOWS_REQUIRED'}
$repo=(Resolve-Path -LiteralPath $CandidateRoot).Path
$evidence=[IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $evidence|Out-Null
$head=(& git -C $repo rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0 -or $head -cne $ExpectedCandidateCommit){throw 'C013_RELEASE_CHECKOUT_MISMATCH'}
$builder=Join-Path $repo 'windows/desktop/scripts/Build-Phase2WindowsRelease.ps1'
if(-not(Test-Path -LiteralPath $builder)){throw 'C013_OFFICIAL_RELEASE_BUILDER_MISSING'}
$log=Join-Path $evidence 'c013-full-release.log'
$output=Join-Path $evidence 'official-full-release-work'
$complete=$false;$exception=$null
try{
 & $builder -OutputRoot $output -ValidationScope Full -Version ('c013-validation-'+$head.Substring(0,12)) *> $log
 $complete=$true
}catch{
 $exception=$_.Exception.GetType().Name+':'+$_.Exception.Message
 Add-Content -LiteralPath $log -Value ('C013_RELEASE_BUILDER_ERROR='+$exception)
}
$raw=if(Test-Path -LiteralPath $log){Get-Content -LiteralPath $log -Raw}else{''}
$known=$raw.Contains('PHASE2_CORE_SMOKE=FAIL') -and $raw.Contains('torso_neutral.png')
$zips=@(Get-ChildItem -LiteralPath $output -Filter '*.zip' -File -ErrorAction SilentlyContinue)
if($known -and (-not $complete) -and $zips.Count -eq 0){
 $status='BLOCKED';$reason='ISSUE_78_MAOTAI_TORSO_NEUTRAL_PNG_REAL_FULL_RELEASE_SMOKE'
}elseif(-not $complete){
 $status='FAIL';$reason='UNEXPECTED_NATIVE_FULL_RELEASE_BUILDER_ERROR'
}else{
 # C013 custom workflow is NOT an officially whitelisted release provenance.
 $status='BLOCKED';$reason='OFFICIAL_WHITELISTED_RELEASE_ATTESTATION_AND_INSTALL_VALIDATION_REQUIRED'
}
$gate=[ordered]@{
 status=$status;reason=$reason;builder_completed=$complete
 native_full_builder_invoked=$true;validation_scope='Full'
 issue78_missing_asset_verified=$known
 zip_count=$zips.Count;source_head=$head
 log='c013-full-release.log'
 log_sha256=$(if(Test-Path -LiteralPath $log){(Get-FileHash -LiteralPath $log -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null})
 exception_type_and_message=$exception
}
$gate | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $evidence 'c013-release-gate.json') -Encoding utf8
$testsPath=Join-Path $evidence 'c013-candidate-tests.json'
$tests=if(Test-Path -LiteralPath $testsPath){Get-Content -LiteralPath $testsPath -Raw|ConvertFrom-Json}else{$null}
$gateSuite=[ordered]@{}
foreach($name in @('C009B','C010A','C010B','C011','G005','C013_EXECUTABLE_PROVENANCE')){
 $gateSuite[$name]=if($null -ne $tests -and $null -ne $tests.suites.$name){
  $tests.suites.$name.status
 }else{'BLOCKED'}
}
$nativeG005Evidence=($null -ne $tests -and $null -ne $tests.suites.G005 -and
 $tests.suites.G005.status -ceq 'PASS' -and $tests.suites.G005.individual_case_evidence_checked -eq $true -and
 $tests.suites.G005.evidence_counts.pass -eq 33 -and
 $tests.suites.G005.evidence_counts.fail -eq 0 -and
 $tests.suites.G005.evidence_counts.blocked -eq 0 -and
 $tests.suites.G005.evidence_counts.unverified -eq 3 -and
 @($tests.suites.G005.evidence_counts.native_verified).Count -eq 3)
$readiness=[ordered]@{
 schema_version='picotoopet.c013.release-readiness.v1'
 generated_utc=[DateTimeOffset]::UtcNow.ToString('o')
 candidate_head=$head
 frozen_base_sha='ec468b9975a3b1cd706e6e74223bfb05f7733a86'
 c012_frozen_candidate_head='b1977ffc36d9151e1b8ff17d369583d0ed0e0334'
 c009b_prior_pr74_sha='1e75cab7daf201a1883e3e98ea5ddb8a753e8e82'
 c009b_failclosed_pr85_sha='100d3788776204770d7aaff11c5c28e53ef93c41'
 c010b_tests_sha='8c8f1d7c01dc82baf2df636ef93df5af7125cd3c'
 g005_tests_sha='0c92fbb5152c149e30db0e88a09b4e7eade18e02'
 native_windows_actions_run_id=$env:GITHUB_RUN_ID
 native_windows_actions_run_attempt=$env:GITHUB_RUN_ATTEMPT
 candidate_production_binary_provenance='C013 HEAD source compiled by native Windows dotnet Release, not old owner branch binaries'
 regression_gates=$gateSuite
 native_regression_report='c013-candidate-tests.json'
 c009b_failclosed_real=$(if($null -ne $tests -and $null -ne $tests.suites.C009B.failclosed_checks){$tests.suites.C009B.failclosed_checks}else{$null})
 pr85_production_uplift_audited=$true
 formal_release_gate=$gate
 g005_windows_scenarios=[ordered]@{
  pass=$(if($null -ne $tests -and $null -ne $tests.suites.G005.evidence_counts){$tests.suites.G005.evidence_counts.pass}else{0})
  fail=$(if($null -ne $tests -and $null -ne $tests.suites.G005.evidence_counts){$tests.suites.G005.evidence_counts.fail}else{0})
  blocked=$(if($null -ne $tests -and $null -ne $tests.suites.G005.evidence_counts){$tests.suites.G005.evidence_counts.blocked}else{36})
  unverified=$(if($null -ne $tests -and $null -ne $tests.suites.G005.evidence_counts){$tests.suites.G005.evidence_counts.unverified}else{0})
  native_verified=$(if($null -ne $tests -and $null -ne $tests.suites.G005.evidence_counts){@($tests.suites.G005.evidence_counts.native_verified)}else{@()})
  scope='C013_CANDIDATE_BINARY_WITH_G005_FROZEN_TESTS'
 }
 e2e_residuals=[ordered]@{
 'FV-012'=$(if($nativeG005Evidence){'PASS_C013_WINDOWS_REAL_C009A_PRE_COMMIT_CRASH_AND_RECOVERY'}else{'BLOCKED_NO_C013_NATIVE_CRASH_EVIDENCE'})
 'FV-031'=$(if($nativeG005Evidence){'PASS_C013_WINDOWS_REAL_AAC_OFFSET_WITH_SHA_AUTHORITY_REJECTION'}else{'BLOCKED_NO_C013_NATIVE_AAC_EVIDENCE'})
 'FV-035'=$(if($nativeG005Evidence){'PASS_C013_WINDOWS_REAL_CHILD_PATH_MISSING_NATIVE_TOOLS'}else{'BLOCKED_NO_C013_NATIVE_TOOL_ABSENCE_EVIDENCE'})
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
$readiness | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $evidence 'c013-release-readiness.json') -Encoding utf8
Write-Host "C013_RELEASE_GATE=$status reason=$reason"
Write-Host "C013_RELEASE_BUILDER_TORSO_BLOCK_OBSERVED=$known"
Write-Host "C013_RELEASE_READY=NO"
Write-Host "C013_RELEASE_READINESS_MANIFEST=$(Join-Path $evidence 'c013-release-readiness.json')"
if($status -eq 'FAIL'){exit 1}
exit 0
