# G007 test-owned native Windows published-app acceptance gate.
# NEVER substitute dotnet run/Debug for a formally published Windows executable.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$FrozenCheckout,
    [Parameter(Mandatory)][string]$EvidenceRoot,
    [Parameter(Mandatory)][string]$ExpectedCommit
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

$expectedFrozen = 'ec468b9975a3b1cd706e6e74223bfb05f7733a86'
if ($ExpectedCommit -cne $expectedFrozen) { throw 'FV_PUBLISHED_C011_SHA_NOT_FROZEN' }
if (-not [OperatingSystem]::IsWindows()) { throw 'FV_PUBLISHED_WINDOWS_REQUIRED' }
$source = (Resolve-Path -LiteralPath $FrozenCheckout).Path
$gitHead = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $gitHead -cne $expectedFrozen) { throw 'FV_PUBLISHED_CHECKOUT_SHA_MISMATCH' }
if (-not [IO.Path]::IsPathFullyQualified($EvidenceRoot)) { throw 'FV_PUBLISHED_EVIDENCE_ROOT_NOT_ABSOLUTE' }
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$evidence = [IO.Path]::GetFullPath($EvidenceRoot)
$reportFile = Join-Path $evidence 'published-app-acceptance.json'
$buildLog = Join-Path $evidence 'native-full-release-builder.log'
$builder = Join-Path $source 'windows/desktop/scripts/Build-Phase2WindowsRelease.ps1'
if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) { throw 'FV_PUBLISHED_OFFICIAL_BUILDER_MISSING' }

$session = [Diagnostics.Process]::GetCurrentProcess().SessionId
Push-Location (Join-Path $source 'windows/desktop')
try { $version = (& dotnet --version).Trim() }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0 -or $version -cne '10.0.302') { throw "FV_PUBLISHED_SDK_INCORRECT_$version" }
$stagedRoot = Join-Path $evidence 'official-builder-disposable'
$versionLabel = 'g007-published-validation-' + $ExpectedCommit.Substring(0, 12)
# Exact upstream Full release builder. No bypass, no UiPreview, no generated
# torso asset, and no debug executable ever enters an acceptance path.
$builderCompleted = $false
$builderError = $null
try {
    & $builder -OutputRoot $stagedRoot -ValidationScope Full -Version $versionLabel *> $buildLog
    $builderCompleted = $true
}
catch {
    $builderError = $_.Exception.Message
    Add-Content -LiteralPath $buildLog -Value ('G007_BUILDER_EXCEPTION=' + $builderError)
}
$log = if (Test-Path -LiteralPath $buildLog) {
    Get-Content -LiteralPath $buildLog -Raw
} else { '' }
$matchesKnownGate = $log.Contains('PHASE2_CORE_SMOKE=FAIL') -and
    $log.Contains('torso_neutral.png')
$zipPaths = @(Get-ChildItem -LiteralPath $stagedRoot -Filter '*.zip' -File -ErrorAction SilentlyContinue)
$reportPath = Join-Path $stagedRoot 'windows-build-report.json'
$officialBuilderReport = if (Test-Path -LiteralPath $reportPath) {
    Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
} else { $null }
$builderReportApproved = $false
if ($null -ne $officialBuilderReport) {
    # This G007 workflow is deliberately NOT an approved formal publishing
    # workflow. native_ci_verified is false even when diagnostic build works.
    $builderReportApproved = $officialBuilderReport.native_ci_verified -eq $true -and
        $officialBuilderReport.user_install_allowed -eq $true -and
        $officialBuilderReport.validation_scope -ceq 'full-release'
}
if ($matchesKnownGate) {
    if ($builderCompleted -or $zipPaths.Count -ne 0) {
        throw 'FV_PUBLISHED_BLOCKED_RELEASE_MUST_NOT_HAVE_A_ZIP'
    }
    $gateStatus = 'BLOCKED'
    $gateReason = 'MAOTAI_TORSO_NEUTRAL_PNG_OFFICIAL_FULL_RELEASE_SMOKE_FAIL'
    $fv033 = 'BLOCKED'
} elseif (-not $builderCompleted) {
    $gateStatus = 'FAIL'
    $gateReason = 'UNEXPECTED_OFFICIAL_FULL_RELEASE_BUILD_ERROR'
    $fv033 = 'BLOCKED'
} elseif (-not $builderReportApproved) {
    $gateStatus = 'UNVERIFIED'
    $gateReason = 'NOT_APPROVED_FORMAL_RELEASE_WORKFLOW_OR_ARTIFACT'
    $fv033 = 'UNVERIFIED'
} else {
    # A future officially approved artifact still needs independent
    # installation and new-user executable execution proof.
    $gateStatus = 'UNVERIFIED'
    $gateReason = 'PUBLISHED_APP_INSTALL_AND_START_NOT_PROVEN'
    $fv033 = 'UNVERIFIED'
}
$logSha = if (Test-Path -LiteralPath $buildLog) {
    (Get-FileHash -LiteralPath $buildLog -Algorithm SHA256).Hash.ToLowerInvariant()
} else { $null }
$cases = @(
    [ordered]@{
        id = 'FV-032'; status = 'UNVERIFIED';
        reason = 'NO_INTERACTIVE_PUBLISHED_GUI_CLICK_EVIDENCE';
        measured = 'No real user-session UIAutomation double/concurrent Open or screenshot capture';
        controls_invoked = 0
    },
    [ordered]@{
        id = 'FV-033'; status = $fv033;
        reason = $gateReason;
        measured = 'Original Full release builder, real native Windows build and Maotai smoke gate';
        controls_invoked = 0
    },
    [ordered]@{
        id = 'FV-034'; status = 'UNVERIFIED';
        reason = 'NO_PUBLISHED_GUI_PID_KILL_AND_NEW_PID_RECOVERY_EVIDENCE';
        measured = 'No real packaged app PID killed, no new app PID with verified durable receipt/master and Open';
        controls_invoked = 0
    }
)
$payload = [ordered]@{
    schema_version = 'picotoopet.windows.published-app-acceptance.v1'
    source_sha = $gitHead
    recorded_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    environment = [ordered]@{
        os = [Environment]::OSVersion.VersionString
        dotnet_sdk = $version
        process_session_id = $session
        user_interactive_property = [Environment]::UserInteractive
        native_github_runner = $env:GITHUB_ACTIONS -eq 'true' -and $env:RUNNER_OS -eq 'Windows'
        live_mac_core_connected = $false
        trusted_published_interactive_desktop_proven = $false
    }
    full_release_gate = [ordered]@{
        status = $gateStatus
        reason = $gateReason
        validation_scope = 'Full'
        official_builder_invoked = $true
        builder_completed = $builderCompleted
        native_maotai_failure_observed = $matchesKnownGate
        formal_approved_artifact = $builderReportApproved
        zip_count = $zipPaths.Count
        log_path = 'native-full-release-builder.log'
        log_sha256 = $logSha
    }
    cases = $cases
    live_mac_core = [ordered]@{
        status = 'UNVERIFIED'
        reason = 'REAL_MAC_CORE_NETWORK_TRANSPORT_AUTHORITY_RECONNECTION_NOT_EXECUTED'
        controlled_core_authority_not_accepted_as_live = $true
    }
}
$payload | ConvertTo-Json -Depth 14 | Set-Content -LiteralPath $reportFile -Encoding utf8
Write-Host "FV_PUBLISHED_GATE=$gateStatus"
Write-Host "FV_PUBLISHED_GATE_REASON=$gateReason"
foreach ($item in $cases) { Write-Host "$($item.id)=$($item.status) reason=$($item.reason)" }
Write-Host 'FV_LIVE_MAC_CORE=UNVERIFIED'
Write-Host "FV_PUBLISHED_EVIDENCE=$reportFile"
# Unexpected release failures must not masquerade as a known safety blocker.
if ($gateStatus -eq 'FAIL') { throw "FV_PUBLISHED_UNEXPECTED_BUILDER_FAILURE; log=$buildLog" }
Write-Host 'FV_PUBLISHED_ACCEPTANCE_CLASSIFICATION=PASS_WITH_EXPLICIT_UNVERIFIED_OR_BLOCKED'
