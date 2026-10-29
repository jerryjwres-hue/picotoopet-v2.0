using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// C009C 尚未接入 Goal Center 的独立协调器。仅消费冻结的上游服务及 Core 计划。
/// 它不选择任意路径、不重写 C004/C007/C008/C009 产物，也不持久化第二套交付状态。
/// </summary>
public sealed class PostProductionDeliveryCoordinator : IPostProductionDeliveryObserver, IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly IFinalVideoAssembler _assembler;
    private readonly Func<string, CancellationToken, Task<NarrationPlanResponseRecord>> _getNarrationPlan;
    private readonly Func<string, CancellationToken, Task<CaptionOverlayPlanResponseRecord>> _getOverlayPlan;
    private readonly Func<NarrationPlanResponseRecord, CancellationToken, Task<NarrationArtifact>> _narration;
    private readonly Func<FinalVideoArtifact, CaptionOverlayPlanResponseRecord, CancellationToken, Task<TextOverlayArtifact>> _overlay;
    private readonly Func<MasterCompositionInputV1, CancellationToken, Task<MasterCompositionResult>> _compose;
    private readonly GoalDeliveryCandidateVerifier _verifier;
    private readonly IFinalVideoLauncher _launcher;
    private readonly Func<string, string, CancellationToken, Task<C011QaDeliveryAuthority>>? _authority;
    private readonly Func<FinalVideoQaInputV1, CancellationToken, Task<FinalVideoQaResult>>? _verifyQa;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly HashSet<string> _running = new(StringComparer.Ordinal);
    private readonly HashSet<string> _failed = new(StringComparer.Ordinal);
    private readonly Dictionary<string, DateTimeOffset> _retryAfter = new(StringComparer.Ordinal);
    private readonly Func<DateTimeOffset> _utcNow;
    private readonly TimeSpan _retryDelay;
    private readonly HashSet<Task> _tasks = [];
    private GoalDeliverySnapshot _current = GoalDeliverySnapshot.Idle(null, null);
    private GoalDeliveryCandidateV1? _candidate;
    private FinalVideoQaInputV1? _approvedInput;
    private FinalVideoQaResult? _approvedReceipt;
    private string? _approvedAuthorityFingerprint;
    private bool _disposed;
    private bool _opening;
    private readonly VerifiedGoalDeliveryProjectionStore? _durableProjection;
    private bool _backgroundProduction;

    /// <summary>
    /// 依赖均由调用方注入，特意不依赖未经 Windows 验收的 C009B concrete composer。
    /// 接入 ControlCenterSession 须等 C009B 真实 Windows PASS。
    /// </summary>
    public PostProductionDeliveryCoordinator(
        IFinalVideoAssembler assembler,
        Func<string, CancellationToken, Task<NarrationPlanResponseRecord>> getNarrationPlan,
        Func<string, CancellationToken, Task<CaptionOverlayPlanResponseRecord>> getOverlayPlan,
        Func<NarrationPlanResponseRecord, CancellationToken, Task<NarrationArtifact>> narration,
        Func<FinalVideoArtifact, CaptionOverlayPlanResponseRecord, CancellationToken, Task<TextOverlayArtifact>> overlay,
        Func<MasterCompositionInputV1, CancellationToken, Task<MasterCompositionResult>> compose,
        GoalDeliveryCandidateVerifier verifier,
        IFinalVideoLauncher launcher,
        Func<string, string, CancellationToken, Task<C011QaDeliveryAuthority>>? authority = null,
        Func<FinalVideoQaInputV1, CancellationToken, Task<FinalVideoQaResult>>? verifyQa = null,
        VerifiedGoalDeliveryProjectionStore? durableProjection = null,
        bool backgroundProduction = true,
        Func<DateTimeOffset>? utcNow = null,
        TimeSpan? retryDelay = null)
    {
        _durableProjection = durableProjection;
        _backgroundProduction = backgroundProduction;
        // ── A transient postproduction outage must not permanently poison a ready Core job. ──
        _utcNow = utcNow ?? (() => DateTimeOffset.UtcNow);
        _retryDelay = retryDelay ?? TimeSpan.FromMinutes(2);
        if (_retryDelay <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(retryDelay));
        _assembler = assembler ?? throw new ArgumentNullException(nameof(assembler));
        _getNarrationPlan = getNarrationPlan ?? throw new ArgumentNullException(nameof(getNarrationPlan));
        _getOverlayPlan = getOverlayPlan ?? throw new ArgumentNullException(nameof(getOverlayPlan));
        _narration = narration ?? throw new ArgumentNullException(nameof(narration));
        _overlay = overlay ?? throw new ArgumentNullException(nameof(overlay));
        _compose = compose ?? throw new ArgumentNullException(nameof(compose));
        _verifier = verifier ?? throw new ArgumentNullException(nameof(verifier));
        _launcher = launcher ?? throw new ArgumentNullException(nameof(launcher));
        _authority = authority;
        _verifyQa = verifyQa;
    }

    /// <summary>Composition root wires only accepted C009B composer through frozen C009A service.</summary>
    public static PostProductionDeliveryCoordinator Create(
        ControlCenterSession session,
        PostProductionMasterCompositorService masterService)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(masterService);
        var narration = WindowsNarrationSynthesisService.CreateDefault();
        var overlays = WindowsCaptionOverlayService.Create();
        var qa = new FinalVideoQaService();
        return new PostProductionDeliveryCoordinator(
            FinalVideoAssemblyService.Create(session),
            session.GetNarrationPlanAsync,
            session.GetCaptionOverlayPlanAsync,
            narration.SynthesizeAsync,
            overlays.ApplyAsync,
            masterService.ComposeAsync,
            GoalDeliveryCandidateVerifier.CreateDefault(),
            new ShellFinalVideoLauncher(),
            (goal, job, ct) => C011QaDeliveryAuthority.FetchAsync(session, goal, job, ct),
            qa.VerifyAsync,
            durableProjection: VerifiedGoalDeliveryProjectionStore.CreateDefault(),
            backgroundProduction: false);
    }

    public GoalDeliverySnapshot CurrentSnapshot
    {
        get { lock (_gate) { return _current; } }
    }

    /// <summary>Only the independent same-EXE background worker may enable postproduction.</summary>
    internal void EnableBackgroundProduction()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_durableProjection is null)
            {
                throw new InvalidOperationException("GOAL_DELIVERY_PERSISTENCE_REQUIRED");
            }
            _backgroundProduction = true;
        }
    }

    public GoalDeliverySnapshot Observe(string? goalId, GoalVideoContinuationRecord? continuation)
    {
        string? startGoal = null;
        string? startJob = null;
        string? runKey = null;
        bool runBackground = false;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            var valid = !string.IsNullOrWhiteSpace(goalId)
                && continuation is not null
                && string.Equals(continuation.GoalId, goalId, StringComparison.Ordinal)
                && !string.IsNullOrWhiteSpace(continuation.ProductionJobId)
                && string.Equals(continuation.ProductionStatus, "production_ready", StringComparison.Ordinal);
            var jobId = valid ? continuation!.ProductionJobId : null;
            if (_current.GoalId != goalId || _current.ProductionJobId != jobId || !valid)
            {
                _candidate = null;
                _approvedInput = null;
                _approvedReceipt = null;
                _approvedAuthorityFingerprint = null;
                _current = GoalDeliverySnapshot.Idle(goalId, jobId);
            }
            if (!valid || jobId is null)
            {
                return _current;
            }
            var key = Key(goalId!, jobId);
            if (_candidate is not null
                && _candidate.ProductionJobId == jobId
                && _current.CanOpen)
            {
                return _current;
            }
            if (_failed.Contains(key))
            {
                // Preserve a closed QA-specific failure during repeated Goal Center polling.
                // Never reinterpret a failed receipt/decode as an ordinary pre-QA failure.
                if (_current.Phase != GoalDeliveryPhase.QaFailed)
                {
                    _current = Failed(goalId!, jobId);
                }
                return _current;
            }
            // ── Retry only after cooldown; Core/GPU are never claimed or re-submitted here. ──
            if (_retryAfter.TryGetValue(key, out var resumeAfter))
            {
                if (_utcNow() < resumeAfter) return _current;
                _retryAfter.Remove(key);
            }
            if (_running.Contains(key))
            {
                return _current;
            }
            _running.Add(key);
            runBackground = _backgroundProduction;
            // ── WPF may only read a previously approved persistent receipt. ──
            _current = runBackground
                ? Phase(goalId!, jobId, GoalDeliveryPhase.VisualPreparing)
                : GoalDeliverySnapshot.Idle(goalId, jobId);
            startGoal = goalId;
            startJob = jobId;
            runKey = key;
        }
        if (startJob is not null && startGoal is not null && runKey is not null)
        {
            if (runBackground)
            {
                StartReconciliation(startGoal, startJob, runKey);
            }
            else
            {
                StartReadOnlyRestore(startGoal, startJob, runKey);
            }
        }
        return CurrentSnapshot;
    }

    /// <summary>Only a fresh C010A PASS receipt can authorize the one Goal Center Open action.</summary>
    public async Task<bool> OpenCurrentAsync(CancellationToken cancellationToken = default)
    {
        GoalDeliveryCandidateV1 candidate;
        GoalDeliverySnapshot snapshot;
        FinalVideoQaInputV1 approvedInput;
        FinalVideoQaResult approvedReceipt;
        string authorityFingerprint;
        lock (_gate)
        {
            if (_disposed || _opening || _authority is null || _verifyQa is null
                || _candidate is null || _approvedInput is null || _approvedReceipt is null
                || _approvedAuthorityFingerprint is null
                || !_current.CanOpen || _current.Phase != GoalDeliveryPhase.DeliveryReady
                || _current.ProductionJobId != _candidate.ProductionJobId
                || _candidate.ApprovalReceiptDigest != _approvedReceipt.Receipt.ReceiptDigest
                || !GoalDeliveryPolicy.IsAllowed(_candidate.Kind,
                    _candidate.NarrationRequired, _candidate.OverlaysRequired))
            {
                return false;
            }
            candidate = _candidate;
            snapshot = _current;
            approvedInput = _approvedInput;
            approvedReceipt = _approvedReceipt;
            authorityFingerprint = _approvedAuthorityFingerprint;
            _opening = true;
        }

        try
        {
            return await OpenVerifiedAsync(candidate, snapshot, approvedInput,
                approvedReceipt, authorityFingerprint, cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            lock (_gate) { _opening = false; }
        }
    }

    private async Task<bool> OpenVerifiedAsync(
        GoalDeliveryCandidateV1 candidate, GoalDeliverySnapshot snapshot,
        FinalVideoQaInputV1 approvedInput, FinalVideoQaResult approvedReceipt,
        string authorityFingerprint, CancellationToken ct)
    {
        bool verified;
        try
        {
            ct.ThrowIfCancellationRequested();
            if (_durableProjection is not null && !_backgroundProduction)
            {
                // ── GUI Open must remain backed by the current durable QA index. ─────
                // ── A deleted/replaced projection cannot authorize stale UI memory. ─
                var stored = await _durableProjection.ReadAsync(
                    snapshot.GoalId!, snapshot.ProductionJobId!, ct).ConfigureAwait(false);
                if (stored is null
                    || stored.Candidate != candidate
                    || stored.AuthorityFingerprint != authorityFingerprint
                    || stored.Receipt.Receipt.Outcome != "PASS"
                    || stored.Receipt.Receipt.ReceiptDigest != approvedReceipt.Receipt.ReceiptDigest
                    || stored.Receipt.Receipt.QaInputDigest != approvedReceipt.Receipt.QaInputDigest
                    || !string.Equals(stored.Receipt.ReceiptPath, approvedReceipt.ReceiptPath,
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("GOAL_DELIVERY_PERSISTED_QA_REVOKED");
                }
            }
            var authority = await _authority!(snapshot.GoalId!, snapshot.ProductionJobId!, ct)
                .ConfigureAwait(false);
            if (authority.Fingerprint() != authorityFingerprint)
            {
                verified = false;
            }
            else
            {
                // C010A re-verifies the exact managed candidate, provenance, full decode and
                // immutable PASS receipt. A stale in-memory Ready snapshot has no authority.
                var currentApproval = await _verifyQa!(approvedInput, ct).ConfigureAwait(false);
                verified = C011QaDeliveryAuthority.Approved(candidate, approvedInput, currentApproval)
                    && currentApproval.Receipt.QaInputDigest == approvedReceipt.Receipt.QaInputDigest
                    && currentApproval.Receipt.ReceiptDigest == approvedReceipt.Receipt.ReceiptDigest
                    && string.Equals(currentApproval.ReceiptPath, approvedReceipt.ReceiptPath,
                        StringComparison.OrdinalIgnoreCase)
                    && await _verifier.VerifyAtOpenAsync(candidate, ct).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException)
        {
            return false;
        }
        catch (Exception)
        {
            verified = false;
        }

        lock (_gate)
        {
            if (_disposed || !ReferenceEquals(_candidate, candidate)
                || !ReferenceEquals(_approvedInput, approvedInput)
                || !ReferenceEquals(_approvedReceipt, approvedReceipt)
                || _current.GoalId != snapshot.GoalId
                || _current.ProductionJobId != snapshot.ProductionJobId
                || _current.Phase != GoalDeliveryPhase.DeliveryReady
                || !_current.CanOpen)
            {
                return false;
            }
            if (!verified)
            {
                InvalidateCurrent();
                return false;
            }
            try
            {
                _launcher.Open(candidate.FilePath);
                return true;
            }
            catch (Exception)
            {
                InvalidateCurrent();
                return false;
            }
        }
    }


    /// <summary>Read-only GUI projection: never calls C004, ffmpeg, narration, overlay, or composer.</summary>
    private void StartReadOnlyRestore(string goalId, string jobId, string key)
    {
        Task task;
        lock (_gate)
        {
            if (_disposed)
            {
                _running.Remove(key);
                return;
            }
            task = Task.Run(() => RestoreApprovedAsync(goalId, jobId, key, _lifetime.Token));
            _tasks.Add(task);
        }
        _ = task.ContinueWith(
            completed => { lock (_gate) { _tasks.Remove(completed); } },
            CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
    }

    private async Task RestoreApprovedAsync(
        string goalId, string jobId, string key, CancellationToken cancellationToken)
    {
        try
        {
            if (_durableProjection is null || _authority is null || _verifyQa is null)
            {
                return; // ── Missing authoritative verification never grants GUI Open. ──
            }
            var saved = await _durableProjection.ReadAsync(goalId, jobId, cancellationToken)
                .ConfigureAwait(false);
            if (saved is null)
            {
                return; // ── Background producer has not written a QA-approved result. ──
            }
            var authority = await _authority(goalId, jobId, cancellationToken)
                .ConfigureAwait(false);
            if (!string.Equals(authority.Fingerprint(), saved.AuthorityFingerprint, StringComparison.Ordinal))
            {
                throw new InvalidDataException("GOAL_DELIVERY_AUTHORITY_CHANGED");
            }
            if (saved.Receipt.Receipt.Outcome != "PASS"
                || !ProductionLocalEnvironment.IsOrdinaryFile(saved.Receipt.ReceiptPath)
                || saved.Candidate.ApprovalReceiptDigest != saved.Receipt.Receipt.ReceiptDigest)
            {
                throw new InvalidDataException("GOAL_DELIVERY_STORED_QA_INVALID");
            }
            // ── C010A reopens its exact immutable receipt; no alternate QA or compositor. ──
            var current = await _verifyQa(saved.Input, cancellationToken).ConfigureAwait(false);
            if (!C011QaDeliveryAuthority.Approved(saved.Candidate, saved.Input, current)
                || current.Receipt.ReceiptDigest != saved.Receipt.Receipt.ReceiptDigest
                || current.Receipt.QaInputDigest != saved.Receipt.Receipt.QaInputDigest
                || !string.Equals(current.ReceiptPath, saved.Receipt.ReceiptPath,
                    StringComparison.OrdinalIgnoreCase)
                || !await _verifier.VerifyAtOpenAsync(saved.Candidate, cancellationToken)
                    .ConfigureAwait(false))
            {
                throw new InvalidDataException("GOAL_DELIVERY_STORED_QA_STALE");
            }
            lock (_gate)
            {
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = saved.Candidate;
                    _approvedInput = saved.Input;
                    _approvedReceipt = current;
                    _approvedAuthorityFingerprint = saved.AuthorityFingerprint;
                    _current = Phase(goalId, jobId, GoalDeliveryPhase.DeliveryReady);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // ── Closing WPF cancels only GUI receipt observation, never producer work. ──
        }
        catch (Exception)
        {
            lock (_gate)
            {
                _failed.Add(key);
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = null;
                    _approvedInput = null;
                    _approvedReceipt = null;
                    _approvedAuthorityFingerprint = null;
                    _current = Phase(goalId, jobId, GoalDeliveryPhase.QaFailed);
                }
            }
        }
        finally
        {
            lock (_gate) { _running.Remove(key); }
        }
    }

    private void StartReconciliation(string goalId, string jobId, string key)
    {
        Task task;
        lock (_gate)
        {
            if (_disposed)
            {
                _running.Remove(key);
                return;
            }
            task = Task.Run(() => ReconcileAsync(goalId, jobId, key, _lifetime.Token));
            _tasks.Add(task);
        }
        _ = task.ContinueWith(
            completed => { lock (_gate) { _tasks.Remove(completed); } },
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    private async Task ReconcileAsync(
        string goalId, string jobId, string key, CancellationToken cancellationToken)
    {
        try
        {
            // Requirements come from immutable Core plans; never infer them from available files.
            var narrationTask = _getNarrationPlan(jobId, cancellationToken);
            var overlayTask = _getOverlayPlan(jobId, cancellationToken);
            await Task.WhenAll(narrationTask, overlayTask).ConfigureAwait(false);
            var narrationPlan = await narrationTask.ConfigureAwait(false);
            var overlayPlan = await overlayTask.ConfigureAwait(false);
            NarrationPlanContract.Validate(narrationPlan);
            CaptionOverlayPlanParser.Validate(overlayPlan);
            VerifyPlanPair(jobId, narrationPlan, overlayPlan);
            cancellationToken.ThrowIfCancellationRequested();

            var required = GoalDeliveryPolicy.IsPostProductionRequired(
                narrationPlan.Plan.NarrationRequired, overlayPlan.Plan.OverlaysRequired);
            var c004 = await _assembler.AssembleAsync(jobId, cancellationToken).ConfigureAwait(false);
            if (c004.ProductionJobId != jobId)
            {
                throw new InvalidDataException("GOAL_DELIVERY_C004_LINEAGE_INVALID");
            }
            NarrationArtifact? audio = null;
            TextOverlayArtifact? visualOverlay = null;
            if (required)
            {
                PublishPhase(goalId, jobId, GoalDeliveryPhase.VisualReadyPostProcessing);
                PublishPhase(goalId, jobId, GoalDeliveryPhase.PostProcessing);
                if (narrationPlan.Plan.NarrationRequired)
                {
                    audio = await _narration(narrationPlan, cancellationToken).ConfigureAwait(false);
                }
                if (overlayPlan.Plan.OverlaysRequired)
                {
                    visualOverlay = await _overlay(c004, overlayPlan, cancellationToken).ConfigureAwait(false);
                    if (visualOverlay.Passthrough)
                    {
                        throw new InvalidDataException("GOAL_DELIVERY_OVERLAY_REQUIRED");
                    }
                }
            }

            var masterInput = new MasterCompositionInputV1(
                c004, narrationPlan, audio, overlayPlan, visualOverlay);
            var result = await _compose(masterInput, cancellationToken).ConfigureAwait(false);

            GoalDeliveryCandidateV1 candidate;
            if (required)
            {
                var master = result.Artifact;
                if (!result.Required || result.C004Fallback is not null || master is null
                    || master.ProductionJobId != jobId
                    || master.ProductionPackageId != c004.ProductionPackageId
                    || master.ProductionPackageDigest != c004.ProductionPackageDigest
                    || master.ProductionPlanDigest != narrationPlan.Plan.ProductionPlanDigest
                    || master.TargetRuntimeMs != narrationPlan.Plan.TargetRuntimeMs
                    || master.OutputProfileId != overlayPlan.Plan.OutputProfileId
                    || master.HasAudio != narrationPlan.Plan.NarrationRequired
                    || master.VisualSourceKind != (overlayPlan.Plan.OverlaysRequired
                        ? PostProductionMasterProfiles.C008BVisualKind
                        : PostProductionMasterProfiles.C004VisualKind))
                {
                    throw new InvalidDataException("GOAL_DELIVERY_MASTER_INVALID");
                }
                candidate = await _verifier.FromMasterAsync(
                    master, narrationPlan, overlayPlan, cancellationToken).ConfigureAwait(false);
            }
            else
            {
                var fallback = result.C004Fallback;
                if (result.Required || result.Artifact is not null || fallback is null
                    || fallback.ProductionJobId != jobId
                    || fallback.ProductionPackageId != c004.ProductionPackageId
                    || fallback.ProductionPackageDigest != c004.ProductionPackageDigest
                    || fallback.Sha256 != c004.Sha256 || fallback.Bytes != c004.Bytes)
                {
                    throw new InvalidDataException("GOAL_DELIVERY_FALLBACK_INVALID");
                }
                candidate = await _verifier.FromFallbackAsync(
                    fallback, narrationPlan, overlayPlan, cancellationToken).ConfigureAwait(false);
            }
            // C011 fail-closed QA gate: C004 fallback and C009 master must BOTH pass
            // the same frozen C010A production policy, media full-decode and receipt store.
            if (_authority is null || _verifyQa is null)
            {
                throw new InvalidDataException("C011_QA_GATE_UNAVAILABLE");
            }
            PublishPhase(goalId, jobId, GoalDeliveryPhase.QualityChecking);
            var authority = await _authority(goalId, jobId, cancellationToken).ConfigureAwait(false);
            if (!string.Equals(authority.Goal.GoalId, goalId, StringComparison.Ordinal)
                || !string.Equals(authority.Job.ProductionJobId, jobId, StringComparison.Ordinal))
            {
                throw new InvalidDataException("C011_CORE_AUTHORITY_MISMATCH");
            }
            var input = new FinalVideoQaInputV1(
                authority.Goal, authority.Job, authority.Plan, authority.Package,
                masterInput, required ? result.Artifact : null);
            var receipt = await _verifyQa(input, cancellationToken).ConfigureAwait(false);
            if (!C011QaDeliveryAuthority.Approved(candidate, input, receipt))
            {
                throw new InvalidDataException("C011_QA_RECEIPT_NOT_APPROVED");
            }
            candidate = candidate with { ApprovalReceiptDigest = receipt.Receipt.ReceiptDigest };
            cancellationToken.ThrowIfCancellationRequested();
            // ── Publish the QA-approved projection for the GUI only AFTER durable C010 receipt. ──
            if (_durableProjection is not null)
            {
                await _durableProjection.WriteAsync(
                    new VerifiedGoalDeliveryProjection(
                        goalId, jobId, candidate, input, receipt, authority.Fingerprint()),
                    cancellationToken).ConfigureAwait(false);
            }
            lock (_gate)
            {
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = candidate;
                    _approvedInput = input;
                    _approvedReceipt = receipt;
                    _approvedAuthorityFingerprint = authority.Fingerprint();
                    _current = Phase(goalId, jobId, GoalDeliveryPhase.DeliveryReady);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Shutdown is not durable task failure and must never select C004.
        }
        catch (FinalVideoQaException)
        {
            lock (_gate)
            {
                _failed.Add(key);
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = null;
                    _approvedInput = null;
                    _approvedReceipt = null;
                    _approvedAuthorityFingerprint = null;
                    _current = Phase(goalId, jobId, GoalDeliveryPhase.QaFailed);
                }
            }
        }
        catch (Exception error)
        {
            lock (_gate)
            {
                // ── Missing local tools/roots and transient I/O/network failures are repairable.
                // ── All integrity, QA, and provenance failures remain permanently fail-closed.
                if (IsRetryablePostproductionFailure(error))
                {
                    _retryAfter[key] = _utcNow() + _retryDelay;
                }
                else
                {
                    _failed.Add(key);
                }
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = null;
                    _approvedInput = null;
                    _approvedReceipt = null;
                    _approvedAuthorityFingerprint = null;
                    _current = Failed(goalId, jobId);
                }
            }
        }
        finally
        {
            lock (_gate) { _running.Remove(key); }
        }
    }

    private static bool IsRetryablePostproductionFailure(Exception error)
    {
        // ── InvalidDataException inherits IOException; never retry tampered/provenance input.
        if (error is InvalidDataException or FinalVideoQaException) return false;
        // ── Only known recoverable infrastructure outages may re-observe after cooldown.
        return error is IOException or System.Net.Http.HttpRequestException or TimeoutException
            || (error is InvalidOperationException
                && error.Message is "FINAL_VIDEO_PACKAGE_NOT_FOUND"
                    or "FINAL_VIDEO_FFMPEG_UNAVAILABLE"
                    or "FINAL_VIDEO_FFMPEG_START_FAILED");
    }

    private static void VerifyPlanPair(
        string jobId, NarrationPlanResponseRecord narration, CaptionOverlayPlanResponseRecord overlay)
    {
        var n = narration.Plan;
        var o = overlay.Plan;
        if (n.ProductionJobId != jobId || o.ProductionJobId != jobId
            || n.CreativePackageId != o.CreativePackageId
            || n.CreativePackageDigest != o.CreativePackageDigest
            || n.ProductionPlanDigest != o.ProductionPlanDigest
            || n.TargetRuntimeMs != o.TargetRuntimeMs)
        {
            throw new InvalidDataException("GOAL_DELIVERY_PLAN_LINEAGE_INVALID");
        }
    }

    private bool IsCurrent(string goalId, string jobId) =>
        _current.GoalId == goalId && _current.ProductionJobId == jobId;

    private void PublishPhase(string goalId, string jobId, GoalDeliveryPhase phase)
    {
        lock (_gate)
        {
            if (!_disposed && IsCurrent(goalId, jobId))
            {
                _current = Phase(goalId, jobId, phase);
            }
        }
    }

    private void InvalidateCurrent()
    {
        if (_current.GoalId is { } goal && _current.ProductionJobId is { } job)
        {
            _failed.Add(Key(goal, job));
            _candidate = null;
            _approvedInput = null;
            _approvedReceipt = null;
            _approvedAuthorityFingerprint = null;
            _current = Failed(goal, job);
        }
    }

    private static string Key(string goal, string job) => goal + "\u001f" + job;

    private static GoalDeliverySnapshot Phase(string goal, string job, GoalDeliveryPhase phase) =>
        new(goal, job, phase, phase switch
        {
            GoalDeliveryPhase.VisualPreparing => "正在准备基础视频",
            GoalDeliveryPhase.VisualReadyPostProcessing => "基础画面已完成，正在准备旁白/文字后期",
            GoalDeliveryPhase.PostProcessing => "正在生成最终成片",
            GoalDeliveryPhase.MasteredReady => "最终成片已就绪",
            GoalDeliveryPhase.FallbackReady => "基础视频已就绪，等待 QA 验证",
            GoalDeliveryPhase.QualityChecking => "正在进行最终视频媒体质量与来源校验",
            GoalDeliveryPhase.DeliveryReady => "QA 验收通过，最终成片可打开",
            GoalDeliveryPhase.QaFailed => "最终视频未通过 QA 验证",
            _ => null,
        }, phase == GoalDeliveryPhase.DeliveryReady);

    private static GoalDeliverySnapshot Failed(string goal, string job) =>
        new(goal, job, GoalDeliveryPhase.Failed,
            "最终视频暂未生成成功；已有源产物未被修改。", false);

    public async ValueTask DisposeAsync()
    {
        Task[] tasks;
        lock (_gate)
        {
            if (_disposed) { return; }
            _disposed = true;
            _lifetime.Cancel();
            _candidate = null;
            _approvedInput = null;
            _approvedReceipt = null;
            _approvedAuthorityFingerprint = null;
            tasks = _tasks.ToArray();
        }
        try
        {
            await Task.WhenAll(tasks).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // Expected on shutdown.
        }
        _lifetime.Dispose();
    }
}
