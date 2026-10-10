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
    private readonly CancellationTokenSource _lifetime = new();
    private readonly HashSet<string> _running = new(StringComparer.Ordinal);
    private readonly HashSet<string> _failed = new(StringComparer.Ordinal);
    private readonly HashSet<Task> _tasks = [];
    private GoalDeliverySnapshot _current = GoalDeliverySnapshot.Idle(null, null);
    private GoalDeliveryCandidateV1? _candidate;
    private bool _disposed;

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
        IFinalVideoLauncher launcher)
    {
        _assembler = assembler ?? throw new ArgumentNullException(nameof(assembler));
        _getNarrationPlan = getNarrationPlan ?? throw new ArgumentNullException(nameof(getNarrationPlan));
        _getOverlayPlan = getOverlayPlan ?? throw new ArgumentNullException(nameof(getOverlayPlan));
        _narration = narration ?? throw new ArgumentNullException(nameof(narration));
        _overlay = overlay ?? throw new ArgumentNullException(nameof(overlay));
        _compose = compose ?? throw new ArgumentNullException(nameof(compose));
        _verifier = verifier ?? throw new ArgumentNullException(nameof(verifier));
        _launcher = launcher ?? throw new ArgumentNullException(nameof(launcher));
    }

    public GoalDeliverySnapshot CurrentSnapshot
    {
        get { lock (_gate) { return _current; } }
    }

    public GoalDeliverySnapshot Observe(string? goalId, GoalVideoContinuationRecord? continuation)
    {
        string? startGoal = null;
        string? startJob = null;
        string? runKey = null;
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
                _current = Failed(goalId!, jobId);
                return _current;
            }
            if (_running.Contains(key))
            {
                return _current;
            }
            _running.Add(key);
            _current = Phase(goalId!, jobId, GoalDeliveryPhase.VisualPreparing);
            startGoal = goalId;
            startJob = jobId;
            runKey = key;
        }
        if (startJob is not null && startGoal is not null && runKey is not null)
        {
            StartReconciliation(startGoal, startJob, runKey);
        }
        return CurrentSnapshot;
    }

    public async Task<bool> OpenCurrentAsync(CancellationToken cancellationToken = default)
    {
        GoalDeliveryCandidateV1? candidate;
        GoalDeliverySnapshot snapshot;
        lock (_gate)
        {
            if (_disposed || _candidate is null || !_current.CanOpen
                || !GoalDeliveryPolicy.IsPreQaOpenable(_current.Phase, _candidate.Kind)
                || _current.ProductionJobId != _candidate.ProductionJobId
                || !GoalDeliveryPolicy.IsAllowed(
                    _candidate.Kind, _candidate.NarrationRequired, _candidate.OverlaysRequired))
            {
                return false;
            }
            candidate = _candidate;
            snapshot = _current;
        }

        bool valid;
        try
        {
            valid = await _verifier.VerifyAtOpenAsync(candidate, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return false;
        }

        lock (_gate)
        {
            if (_disposed || !ReferenceEquals(_candidate, candidate)
                || _current.GoalId != snapshot.GoalId
                || _current.ProductionJobId != snapshot.ProductionJobId
                || !_current.CanOpen
                || !GoalDeliveryPolicy.IsPreQaOpenable(_current.Phase, candidate.Kind))
            {
                return false;
            }
            if (!valid)
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

            var result = await _compose(
                new MasterCompositionInputV1(c004, narrationPlan, audio, overlayPlan, visualOverlay),
                cancellationToken).ConfigureAwait(false);

            GoalDeliveryCandidateV1 candidate;
            GoalDeliveryPhase phase;
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
                phase = GoalDeliveryPhase.MasteredReady;
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
                phase = GoalDeliveryPhase.FallbackReady;
            }
            cancellationToken.ThrowIfCancellationRequested();
            lock (_gate)
            {
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = candidate;
                    _current = Phase(goalId, jobId, phase);
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Shutdown is not durable task failure and must never select C004.
        }
        catch (Exception)
        {
            lock (_gate)
            {
                _failed.Add(key);
                if (!_disposed && IsCurrent(goalId, jobId))
                {
                    _candidate = null;
                    _current = Failed(goalId, jobId);
                }
            }
        }
        finally
        {
            lock (_gate) { _running.Remove(key); }
        }
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
            GoalDeliveryPhase.FallbackReady => "最终视频已就绪",
            _ => null,
        }, phase is GoalDeliveryPhase.MasteredReady or GoalDeliveryPhase.FallbackReady);

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
