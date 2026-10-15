[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$CandidateRoot,
 [Parameter(Mandatory)][string]$C010BRoot,
 [Parameter(Mandatory)][string]$G005Root,
 [Parameter(Mandatory)][string]$EvidenceDirectory,
 [Parameter(Mandatory)][string]$ExpectedCandidateCommit
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$PSNativeCommandUseErrorActionPreference=$false
if(-not [OperatingSystem]::IsWindows()){throw 'C012_WINDOWS_REQUIRED'}
$candidate=(Resolve-Path -LiteralPath $CandidateRoot).Path
$g006=(Resolve-Path -LiteralPath $C010BRoot).Path
$g005=(Resolve-Path -LiteralPath $G005Root).Path
$evidence=[IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $evidence|Out-Null
$sourceBase='ec468b9975a3b1cd706e6e74223bfb05f7733a86'
$c009b='1e75cab7daf201a1883e3e98ea5ddb8a753e8e82'
$c010b='8c8f1d7c01dc82baf2df636ef93df5af7125cd3c'
$g005Sha='99cccbb867c3c4d532e816907f2350a0c6d043e0'
function Head([string]$root){
 $v=(& git -C $root rev-parse HEAD).Trim()
 if($LASTEXITCODE -ne 0){throw "C012_GIT_REV_PARSE_ERROR=$root"}
 return $v
}
if((Head $candidate) -cne $ExpectedCandidateCommit -or
   (Head $g006) -cne $c010b -or (Head $g005) -cne $g005Sha){
 throw 'C012_DISPOSABLE_CHECKOUT_SHA_MISMATCH'
}
$expectedBlobs=[ordered]@{
 'windows/desktop/src/PicotooPet.Desktop/Services/FixedFfmpegMasterVideoComposer.cs'='53609c0c78dd6e8c1189a865b04b1aaaec1c39df'
 'windows/desktop/src/PicotooPet.Desktop/Services/MasterVideoMediaProbe.cs'='8b998f9de7820f8bdebaad011b471164eeb59359'
 'windows/desktop/src/PicotooPet.Desktop/Services/MasterVideoProcessRunner.cs'='e82e72f086a84867c0c38ebe4e6e5ff689385dfa'
 'windows/desktop/src/PicotooPet.Desktop/Services/FinalVideoQaService.cs'=''; 
 'windows/desktop/src/PicotooPet.Desktop/Services/PostProductionDeliveryCoordinator.cs'=''
 'windows/desktop/src/PicotooPet.Desktop/ViewModels/GoalVideoContinuationViewModel.cs'=''
}
# The frozen C011 SHA is the Git baseline for QA/Goal source; assert equality
# using git's own object identity rather than copying another owner's code.
foreach($p in @($expectedBlobs.Keys)){
 $blob=(& git -C $candidate rev-parse "HEAD:$p").Trim()
 if($LASTEXITCODE -ne 0){throw "C012_BLOB_MISSING=$p"}
 if($expectedBlobs[$p]){
  if($blob -cne $expectedBlobs[$p]){throw "C012_HARDENING_BLOB_MISMATCH=$p"}
 }else{
  $frozen=(& git -C $candidate rev-parse "$($sourceBase):$p").Trim()
  if($LASTEXITCODE -ne 0 -or $blob -cne $frozen){throw "C012_FROZEN_C011_PRODUCTION_CHANGED=$p"}
 }
}
Write-Host 'C012_PRODUCTION_BLOB_PINS=PASS'
function Overlay([string]$ownerRoot,[string]$relative){
 $from=Join-Path $ownerRoot $relative
 $to=Join-Path $candidate $relative
 if(-not(Test-Path -LiteralPath $from -PathType Container)){throw "C012_TEST_OVERLAY_SOURCE_MISSING=$relative"}
 if(Test-Path -LiteralPath $to){throw "C012_TEST_OVERLAY_OWNERSHIP_COLLISION=$relative"}
 Copy-Item -LiteralPath $from -Destination $to -Recurse
}
Overlay $g006 'windows/desktop/tests/PicotooPet.FinalVideoQa.IntegrationTests'
Overlay $g005 'windows/desktop/tests/PicotooPet.G005.FinalVideoE2E.SmokeTests'
$results=[ordered]@{}
function Suite([string]$name,[string]$project,[string[]]$programArgs,[string[]]$markers){
 $log=Join-Path $evidence "$name.log"
 $all=@('run','--project',(Join-Path $candidate $project),'-c','Release','--no-launch-profile') + $programArgs
 $exit=-1;$err=$null
 Push-Location (Join-Path $candidate 'windows/desktop')
 try {
   & dotnet @all *> $log
   $exit=$LASTEXITCODE
 } catch {
   $err=$_.Exception.GetType().Name+':'+$_.Exception.Message
   Add-Content -LiteralPath $log -Value "C012_SUITE_COMMAND_EXCEPTION=$err"
 } finally { Pop-Location }
 $raw=if(Test-Path -LiteralPath $log){Get-Content -LiteralPath $log -Raw}else{''}
 $missing=@($markers | Where-Object {-not $raw.Contains($_)})
 $status=if($exit -eq 0 -and $missing.Count -eq 0 -and $null -eq $err){'PASS'}else{'FAIL'}
 $results[$name]=[ordered]@{
   status=$status;scope='C012_PRODUCTION_BINARY_WITH_FROZEN_OWNER_TEST_HARNESS'
   test_project=$project;markers=$markers;missing_markers=$missing
   exit_code=$exit;exception=$err;log="$name.log"
   log_sha256=$(if(Test-Path -LiteralPath $log){(Get-FileHash $log -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null})
 }
 Write-Host "C012_SUITE_$name=$status exit=$exit missing=$($missing.Count)"
 return $raw
}
$mux=Suite 'C009B' 'windows/desktop/tests/PicotooPet.PostProductionMasterMux.SmokeTests/PicotooPet.PostProductionMasterMux.SmokeTests.csproj' @() @(
 'MASTER_MUX_UNIT=PASS','MASTER_MUX_REAL_WINDOWS=PASS',
 'MASTER_MUX_HARDENING_UNIT=PASS','MASTER_MUX_HARDENING_REAL=PASS')
$qa=Suite 'C010A' 'windows/desktop/tests/PicotooPet.FinalVideoQa.SmokeTests/PicotooPet.FinalVideoQa.SmokeTests.csproj' @('--','--real') @(
 'QA_MEDIA_POLICY=PASS','QA_LINEAGE_SECURITY_RESTART=PASS',
 'QA_REAL_CORRUPT_PACKET_DECODE_TIMEOUT_CANCEL=PASS')
$qaCount=[regex]::Matches($qa,'(?m)^PASS REAL_WINDOWS video\.(landscape|vertical|square)\.v1 narration=(True|False) overlay=(True|False)\s*$').Count
$results['C010A'].real_profile_modes=$qaCount
if($results['C010A'].status -eq 'PASS' -and $qaCount -ne 12){
 $results['C010A'].status='FAIL';$results['C010A'].missing_markers=@("12_real_profile_modes_observed=$qaCount")
}
Write-Host "C012_C010A_NATIVE_PROFILE_MODES=$qaCount"
$c010bOut=Suite 'C010B' 'windows/desktop/tests/PicotooPet.FinalVideoQa.IntegrationTests/PicotooPet.FinalVideoQa.IntegrationTests.csproj' @('--','--real') @(
 'C010B_INTEGRATION_SUMMARY=passed=17;failed=0;real=True',
 'C010B_REAL_MASTER_MANIFEST_SUMMARY=passed=17;failed=0;source=C009B_REAL',
 'C010B_THREE_PROFILE_REAL_SUMMARY=passed=12;failed=0')
$groupCount=[regex]::Matches($c010bOut,'(?m)^C010B_PASS ').Count
$negativeCount=[regex]::Matches($c010bOut,'(?m)^C010B_MASTER_MANIFEST_NEGATIVE_PASS ').Count
$nativeCount=[regex]::Matches($c010bOut,'(?m)^C010B_THREE_PROFILE_REAL_PASS ').Count
$results['C010B'].evidence_counts=[ordered]@{groups=$groupCount;master_negative=$negativeCount;three_profiles=$nativeCount}
if($results['C010B'].status -eq 'PASS' -and ($groupCount -ne 17 -or $negativeCount -ne 17 -or $nativeCount -ne 12)){
 $results['C010B'].status='FAIL';$results['C010B'].missing_markers=@("unique_evidence_counts=$groupCount/$negativeCount/$nativeCount")
}
Write-Host "C012_C010B_REAL_COUNTS=groups:$groupCount;master_negative:$negativeCount;profiles:$nativeCount"
$c011=Suite 'C011' 'windows/desktop/tests/PicotooPet.FinalDeliveryIntegration.SmokeTests/PicotooPet.FinalDeliveryIntegration.SmokeTests.csproj' @() @(
 'C011_MODE_N0_O0=PASS','C011_MODE_N1_O0=PASS',
 'C011_MODE_N0_O1=PASS','C011_MODE_N1_O1=PASS',
 'C011_RECEIPT_TAMPER=PASS','C011_CHANGED_PROVENANCE=PASS',
 'C011_REQUIRED_MASTER_NO_FALLBACK=PASS','C011_FULL_DECODE_REJECTION=PASS',
 'C011_DURABLE_RESTART=PASS','C011_SINGLE_ASYNC_OPEN=PASS',
 'C011_JOB_SWITCH=PASS','C011_CANCEL_DISPOSE=PASS',
 'FINAL_VIDEO_QA_GATED_INTEGRATION=PASS')
$g005ResultFile=Join-Path $evidence 'g005-independent-36.json'
$g005Raw=Suite 'G005' 'windows/desktop/tests/PicotooPet.G005.FinalVideoE2E.SmokeTests/PicotooPet.G005.FinalVideoE2E.SmokeTests.csproj' @('--','--report',$g005ResultFile) @(
 'FV_G005_SUMMARY PASS=30 FAIL=0 BLOCKED=3 UNVERIFIED=3')
$validG005=$false
if(Test-Path -LiteralPath $g005ResultFile){
 try{
  $g005Report=Get-Content -LiteralPath $g005ResultFile -Raw|ConvertFrom-Json
  $passCases=@($g005Report.cases|Where-Object {$_.status -eq 'PASS'})
  $all36=@($g005Report.cases)
  $n=@($passCases|Where-Object {$_.assertions -ge 1 -and
    $g005Raw.Contains("$($_.id)=PASS scope=") }).Count
  $validG005=($g005Report.c011_sha -cne $null -and $all36.Count -eq 36 -and
    $passCases.Count -eq 30 -and $n -eq 30 -and
    @($all36|Where-Object {$_.status -eq 'BLOCKED'}).Count -eq 3 -and
    @($all36|Where-Object {$_.status -eq 'UNVERIFIED'}).Count -eq 3)
 }catch{$validG005=$false}
}
$results['G005'].individual_case_evidence_checked=$validG005
if($results['G005'].status -eq 'PASS' -and -not $validG005){
 $results['G005'].status='FAIL';$results['G005'].missing_markers=@('G005_30_independent_case_oracles')
}
Write-Host "C012_G005_INDEPENDENT_CASES=$validG005"
$scriptReport=[ordered]@{
 schema_version='picotoopet.c012.candidate-regression.v1'
 candidate_head=$ExpectedCandidateCommit
 c011_frozen_source=$sourceBase
 c009b_hardening=$c009b
 c010b_frozen_tests=$c010b
 g005_frozen_tests=$g005Sha
 git_blob_pins_pass=$true
 sdk=$(& dotnet --version)
 os=[Environment]::OSVersion.VersionString
 github_run_id=$env:GITHUB_RUN_ID
 github_run_attempt=$env:GITHUB_RUN_ATTEMPT
 created_utc=[DateTimeOffset]::UtcNow.ToString('o')
 suites=$results
 failure_count=@($results.Values|Where-Object {$_.status -eq 'FAIL'}).Count
}
$scriptReport|ConvertTo-Json -Depth 25|Set-Content -LiteralPath (Join-Path $evidence 'c012-candidate-tests.json') -Encoding utf8
Write-Host "C012_CANDIDATE_REGRESSION_FAIL=$($scriptReport.failure_count)"
# Do not suppress regression failures; separate release gate step still runs with if:always().
if($scriptReport.failure_count -gt 0){exit 1}
Write-Host 'C012_CANDIDATE_REGRESSION=PASS'
