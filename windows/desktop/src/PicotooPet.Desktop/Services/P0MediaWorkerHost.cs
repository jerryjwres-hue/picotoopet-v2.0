using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Logging;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Services;

/// <summary>
/// P0 原生 Windows 无窗口执行入口。独立进程持有自身 Session 和固定 Comfy executor；
/// WPF 关闭、最小化和页面切换都不拥有或取消任何 GPU lease。
/// </summary>
public static class P0MediaWorkerHost
{
    private static readonly TimeSpan PollInterval = TimeSpan.FromSeconds(15);
    private static readonly TimeSpan FailureBackoff = TimeSpan.FromMinutes(2);
    private const string ExplicitStopEventName = @"Local\PicotooPetV2.P0MediaWorker.ExplicitExit";

    /// <summary>Only explicit Exit stops background work; ordinary WPF close never signals.</summary>
    public static void RequestExplicitStop()
    {
        // ── AutoReset signal is owned by the current user session, not a service. ──
        using var signal = new EventWaitHandle(
            initialState: false, mode: EventResetMode.AutoReset, name: ExplicitStopEventName);
        signal.Set();
    }

    public static async Task<int> RunAsync(CancellationToken cancellationToken)
    {
        // ── 同一用户会话最多一个 GPU host，杜绝多个 WPF 窗口同时发起渲染。 ──
        using var mutex = new Mutex(initiallyOwned: false, @"Local\PicotooPetV2.P0MediaWorker");
        bool acquired;
        try
        {
            acquired = mutex.WaitOne(TimeSpan.Zero);
        }
        catch (AbandonedMutexException)
        {
            // ── Previous GPU host crashed; its abandoned lock must not block restart. ──
            acquired = true;
        }
        if (!acquired)
        {
            return 0;
        }
        // ── Explicit Exit is cooperative: finish any started GPU call before exiting. ──
        using var stopSignal = new EventWaitHandle(
            initialState: false, mode: EventResetMode.AutoReset, name: ExplicitStopEventName);

        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PicotooPetV2", "Desktop");
        var logger = new SafeFileLogger(Path.Combine(root, "logs", "media-worker.log"));
        try
        {
            var session = new ControlCenterSession(
                new CredentialManagerTokenStore(),
                new DesktopSettingsStore(Path.Combine(root, "settings.json")),
                logger,
                new ConnectionStateStore(),
                new CapabilityStateStore(),
                new TaskStateStore());

            // ── Only this independent same-EXE host may assemble and QA final videos. ──
            session.EnableHeadlessFinalVideoProduction();
            // ── Worker 按计划串行执行 GPU，不自建数据库或第二套 Comfy client。 ──
            await using (session)
            await using (var executor = ProductionExecutionService.Create(session, shot =>
                logger.Info($"P0_SHOT_METRIC job={shot.JobId} task={shot.TaskId} attempts_at_claim={shot.AttemptCountAtClaim} known_prompt={shot.KnownPromptAtClaim} wall_ms={shot.WallElapsedMs} result={shot.ResultCode} visual_quality=UNVERIFIED"),
                (jobId, digest) => P0ThreeShotAcceptanceGate.AcquireSubmissionPermit(jobId, digest)))
            {
                // ── Durable uncertainty is consulted before all newly-discovered Goal work. ──
                var journal = new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot);
                using var reconciler = ComfyPromptReconciler.Create();
                var pendingRecovery = new ProductionPendingRecovery(
                    journal, reconciler, session.GetProductionJobAsync);
                var backoff = new System.Collections.Generic.Dictionary<string, DateTimeOffset>(
                    StringComparer.Ordinal);
                var connected = false;
                var explicitStop = false;
                while (!cancellationToken.IsCancellationRequested && !explicitStop)
                {
                    // ── A normal window close does not signal; explicit Exit does. ──
                    if (stopSignal.WaitOne(0))
                    {
                        break;
                    }
                    try
                    {
                        if (!connected)
                        {
                            await session.InitializeAsync(cancellationToken).ConfigureAwait(false);
                            connected = true;
                        }
                        // ── Fail-closed: terminal/draining/unknown GPU journal always wins. ──
                        var pending = await pendingRecovery.ReconcileAsync(cancellationToken)
                            .ConfigureAwait(false);
                        if (pending.HasPending)
                        {
                            // ── Recover exactly one known job, never enumerate fresh GPU work. ──
                            var resumeJobId = pending.RecoverableJobId;
                            if (!string.IsNullOrWhiteSpace(resumeJobId)
                                // ── 未指定放行的旧 job 只允许只读 journal 对账，不得新 POST。 ──
                                && await P0ThreeShotAcceptanceGate.AllowsJobAsync(
                                    session, resumeJobId, cancellationToken).ConfigureAwait(false)
                                && (!backoff.TryGetValue(resumeJobId, out var resumeAfter)
                                    || resumeAfter <= DateTimeOffset.UtcNow))
                            {
                                try
                                {
                                    _ = await executor.RunAsync(resumeJobId, cancellationToken)
                                        .ConfigureAwait(false);
                                    backoff.Remove(resumeJobId);
                                }
                                catch (Exception error) when (!cancellationToken.IsCancellationRequested)
                                {
                                    // ── The unresolved journal persists; no alternate POST follows. ──
                                    logger.Error("P0 journal 恢复失败，禁止调度新 GPU 作业", error);
                                    backoff[resumeJobId] = DateTimeOffset.UtcNow + FailureBackoff;
                                }
                            }
                        }
                        else
                        {
                        var goals = await session.GetGoalsAsync(cancellationToken).ConfigureAwait(false);
                        foreach (var goal in goals)
                        {
                            cancellationToken.ThrowIfCancellationRequested();
                            if (stopSignal.WaitOne(0))
                            {
                                // ── Stop between jobs, never revoke an in-flight Comfy prompt. ──
                                explicitStop = true;
                                break;
                            }
                            if (goal.IntentType is not ("video.creative" or "product.research_to_video"))
                            {
                                continue;
                            }
                            PicotooPet.Desktop.Core.Contracts.GoalVideoContinuationRecord continuation;
                            try
                            {
                                continuation = await session.GetGoalVideoContinuationAsync(
                                    goal.GoalId, cancellationToken).ConfigureAwait(false);
                            }
                            catch (PicotooPet.Desktop.Core.Networking.ApiException ex) when (ex.StatusCode == 404)
                            {
                                // ── 本地 Creative 尚未通过质量门；不创建人工 WebGPT 占位返回。 ──
                                continue;
                            }

                            var jobId = continuation.ProductionJobId;
                            if (string.IsNullOrWhiteSpace(jobId))
                            {
                                continue;
                            }
                            // ── 默认文件不存在时沿用原调度；验收模式仅核准一个冻结三镜头 Job。 ──
                            if (!await P0ThreeShotAcceptanceGate.AllowsJobAsync(
                                session, jobId, cancellationToken).ConfigureAwait(false))
                            {
                                continue;
                            }
                            if (continuation.ProductionStatus is "production_ready")
                            {
                                // ── 已完成镜头走冻结 C009/C010/C011 合成与 QA 流。 ──
                                _ = session.FinalVideoDelivery.Observe(goal.GoalId, continuation);
                                continue;
                            }
                            if (continuation.ProductionStatus is not ("Ready" or "Claimed" or "Rendering"))
                            {
                                continue;
                            }
                            if (backoff.TryGetValue(jobId, out var after) && after > DateTimeOffset.UtcNow)
                            {
                                continue;
                            }
                            try
                            {
                                _ = await executor.RunAsync(jobId, cancellationToken).ConfigureAwait(false);
                                backoff.Remove(jobId);
                            }
                            catch (Exception error) when (!cancellationToken.IsCancellationRequested)
                            {
                                // ── 模型缺失/不确定 submit 等待修复，不在循环中热重投 GPU。 ──
                                logger.Error("P0 生产工作失败，已实施有界退避", error);
                                backoff[jobId] = DateTimeOffset.UtcNow + FailureBackoff;
                            }
                        }
                        } // ── End fresh Goal dispatch, only allowed with zero pending journal. ──
                    }
                    catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
                    {
                        break;
                    }
                    catch (Exception error)
                    {
                        // ── Only reinitialize after an actual Core failure; no 15s churn. ──
                        connected = false;
                        logger.Error("P0 Mac Core 检查失败", error);
                    }
                    if (explicitStop || stopSignal.WaitOne(0))
                    {
                        break;
                    }
                    await Task.Delay(PollInterval, cancellationToken).ConfigureAwait(false);
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            logger.Error("P0 独立媒体 Worker 启动失败", error);
            return 1;
        }
        finally
        {
            await logger.DisposeAsync().ConfigureAwait(false);
        }
    }
}
