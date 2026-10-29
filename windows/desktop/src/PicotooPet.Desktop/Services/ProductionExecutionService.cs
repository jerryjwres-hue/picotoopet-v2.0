using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Runtime.CompilerServices;

using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

[assembly: InternalsVisibleTo("PicotooPet.MediaWorker.SmokeTests")]

namespace PicotooPet.Desktop.Services;

/// <summary>Non-aesthetic progress observation: wall duration is NOT measured GPU busy time.</summary>
public sealed record ProductionShotObservation(
    string JobId, string TaskId, int AttemptCountAtClaim,
    bool KnownPromptAtClaim, long WallElapsedMs, string ResultCode);

/// <summary>2.3.20.1 Windows 本地 GPU executor；只执行 Core 已冻结的 Production Plan。</summary>
public sealed class ProductionExecutionService : IProductionJobExecutor, IAsyncDisposable
{
    private static readonly string[] RequiredNodeClasses =
    [
        "UNETLoader",
        "CLIPLoader",
        "VAELoader",
        "ModelSamplingSD3",
        "CLIPTextEncode",
        "Wan22ImageToVideoLatent",
        "KSampler",
        "VAEDecode",
        "SaveWEBM",
        "LoadImage",
    ];

    private static readonly string[] RequiredModelFiles =
    [
        "wan2.2_ti2v_5B_fp16.safetensors",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "wan2.2_vae.safetensors",
    ];

    private readonly IProductionExecutionGateway _session;
    private readonly ProductionSubmissionJournal _journal;
    private readonly IComfyPromptReconciler _reconciler;
    private readonly Func<CancellationToken, Task<ProductionPreflightSnapshot>>? _preflightOverride;
    private readonly TimeSpan _pollInterval = TimeSpan.FromSeconds(2);
    private readonly TimeSpan _heartbeatInterval = TimeSpan.FromSeconds(30);
    private readonly TimeSpan _historyTimeout = TimeSpan.FromMinutes(20);
    private readonly ComfyProductionClient _comfy;
    private readonly bool _ownsComfy;
    private readonly string _executorId;
    private readonly Action<ProductionShotObservation>? _shotObserver;
    private readonly Func<string, string, IDisposable?>? _submissionPermit;
    private readonly Func<string, CancellationToken, Task<bool>>? _acceptanceAdmission;

    // Dependency composition only; no public flag/environment switch can arm shipping I2V.
    internal ProductionReferenceSnapshotStore? ReferenceSnapshots { get; init; }

    public ProductionExecutionService(
        ControlCenterSession session,
        ComfyProductionClient comfy,
        string? executorId = null)
    {
        _session = new SessionGateway(session ?? throw new ArgumentNullException(nameof(session)));
        _journal = new(ProductionSubmissionJournal.DefaultRoot);
        _reconciler = ComfyPromptReconciler.Create();
        _comfy = comfy ?? throw new ArgumentNullException(nameof(comfy));
        _ownsComfy = false;
        _executorId = NormalizeExecutorId(executorId ?? $"windows-production-{Environment.MachineName}");
        _submissionPermit = P0ThreeShotAcceptanceGate.AcquireSubmissionPermit;
        _acceptanceAdmission = (job, ct) => P0ThreeShotAcceptanceGate.AllowsJobAsync(session, job, ct);
    }

    private ProductionExecutionService(
        ControlCenterSession session,
        ComfyProductionClient comfy,
        string executorId,
        bool ownsComfy,
        Action<ProductionShotObservation>? shotObserver = null,
        Func<string, string, IDisposable?>? submissionPermit = null)
    {
        _session = new SessionGateway(session);
        _journal = new(ProductionSubmissionJournal.DefaultRoot);
        _reconciler = ComfyPromptReconciler.Create();
        _comfy = comfy;
        _executorId = executorId;
        _ownsComfy = ownsComfy;
        _shotObserver = shotObserver;
        _submissionPermit = submissionPermit ?? P0ThreeShotAcceptanceGate.AcquireSubmissionPermit;
        _acceptanceAdmission = (job, ct) => P0ThreeShotAcceptanceGate.AllowsJobAsync(session, job, ct);
    }

    /// <summary>同一 executor 的独立用户进程组合；不创建 WPF 会话。</summary>
    public ProductionExecutionService(IProductionExecutionGateway gateway, ComfyProductionClient comfy)
        : this(gateway, comfy, new(ProductionSubmissionJournal.DefaultRoot), ComfyPromptReconciler.Create(), null) { }

    public ProductionExecutionService(IProductionExecutionGateway gateway, ComfyProductionClient comfy,
        ProductionSubmissionJournal journal, IComfyPromptReconciler reconciler,
        Func<CancellationToken, Task<ProductionPreflightSnapshot>>? preflight = null,
        TimeSpan? pollInterval = null, TimeSpan? heartbeatInterval = null, TimeSpan? historyTimeout = null,
        Action<ProductionShotObservation>? shotObserver = null,
        Func<string, string, IDisposable?>? submissionPermit = null,
        Func<string, CancellationToken, Task<bool>>? acceptanceAdmission = null)
    {
        _session = gateway; _comfy = comfy; _journal = journal; _reconciler = reconciler;
        _preflightOverride = preflight;
        _shotObserver = shotObserver;
        _submissionPermit = submissionPermit;
        _acceptanceAdmission = acceptanceAdmission;
        _executorId = NormalizeExecutorId($"windows-production-{Environment.MachineName}");
        _pollInterval = pollInterval ?? TimeSpan.FromSeconds(2);
        _heartbeatInterval = heartbeatInterval ?? TimeSpan.FromSeconds(30);
        _historyTimeout = historyTimeout ?? TimeSpan.FromMinutes(20);
        if (_pollInterval <= TimeSpan.Zero || _heartbeatInterval <= TimeSpan.Zero || _historyTimeout <= TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(pollInterval));
    }

    /// <summary>创建正式固定 loopback executor；没有 endpoint 参数。</summary>
    public static ProductionExecutionService Create(
        ControlCenterSession session, Action<ProductionShotObservation>? shotObserver = null,
        Func<string, string, IDisposable?>? submissionPermit = null) =>
        new(
            session,
            ComfyProductionClient.Create(),
            NormalizeExecutorId($"windows-production-{Environment.MachineName}"),
            ownsComfy: true,
            shotObserver: shotObserver,
            submissionPermit: submissionPermit);

    /// <summary>验证本机 ComfyUI、workflow、模型哈希和受信数据根；不提交渲染。</summary>
    public async Task<ProductionPreflightSnapshot> PreflightAsync(
        CancellationToken cancellationToken = default)
    {
        var checks = new List<string>();
        var objectInfo = await _comfy.GetObjectInfoAsync(cancellationToken).ConfigureAwait(false);
        foreach (var className in RequiredNodeClasses)
        {
            if (!objectInfo.ContainsKey(className))
            {
                return ProductionPreflightSnapshot.Failed(
                    $"ComfyUI 缺少正式 workflow 所需 core node：{className}",
                    checks);
            }
        }
        checks.Add("ComfyUI loopback object_info：PASS");

        // ── 每次 preflight 都重新验证源码内置 workflow，不信任磁盘副本 ──────────
        _ = ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.T2VWorkflowId);
        _ = ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.I2VWorkflowId);
        checks.Add("内置 Wan2.2 workflow allowlist：PASS");

        var manifest = ComfyModelManifestCatalog.Load();
        var modelRoot = Path.GetFullPath(Environment.ExpandEnvironmentVariables(manifest.ModelRoot));
        if (!Directory.Exists(modelRoot))
        {
            return ProductionPreflightSnapshot.Failed($"受信模型根目录不存在：{modelRoot}", checks);
        }
        foreach (var filename in RequiredModelFiles)
        {
            var model = manifest.Models.SingleOrDefault(item =>
                string.Equals(item.Filename, filename, StringComparison.Ordinal));
            if (model is null)
            {
                return ProductionPreflightSnapshot.Failed($"模型 Manifest 缺少：{filename}", checks);
            }
            var modelPath = ResolveUnderRoot(
                modelRoot,
                Path.Combine(model.Destination, model.Filename),
                requireExistingFile: true);
            var actual = await Sha256FileAsync(modelPath, cancellationToken).ConfigureAwait(false);
            if (!string.Equals(actual, model.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                return ProductionPreflightSnapshot.Failed(
                    $"模型 SHA-256 不匹配：{model.Filename}",
                    checks);
            }
        }
        checks.Add("Wan2.2 5B / UMT5 / VAE pinned hashes：PASS");

        var dataRoot = ResolveComfyDataRoot();
        var outputRoot = Path.GetFullPath(Path.Combine(dataRoot, "output"));
        var inputRoot = Path.GetFullPath(Path.Combine(dataRoot, "input"));
        Directory.CreateDirectory(outputRoot);
        Directory.CreateDirectory(inputRoot);
        AssertNoLinkEscape(dataRoot, outputRoot);
        AssertNoLinkEscape(dataRoot, inputRoot);
        checks.Add("Comfy 数据根 / input / output：PASS");

        return new ProductionPreflightSnapshot(
            true,
            "本地 ComfyUI 生产 preflight 通过。",
            dataRoot,
            inputRoot,
            outputRoot,
            modelRoot,
            checks);
    }

    /// <summary>Claim Core job 并逐 shot 执行；任何未批准 intent/workflow 都不会提交到 ComfyUI。</summary>
    public async Task<ProductionPackageRecord> RunAsync(
        string productionJobId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(productionJobId))
        {
            throw new ArgumentException("Production Job ID 不能为空。", nameof(productionJobId));
        }
        // ── 同一真实 Session 门禁同时覆盖独立 Worker 与旧 Production Panel 手动启动。 ──
        if (_acceptanceAdmission is not null
            && !await _acceptanceAdmission(productionJobId, cancellationToken).ConfigureAwait(false))
            throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD");
        using var gpu = _journal.AcquireGpu();
        // A process death releases the lock, not the submission uncertainty of a prior GPU job.
        if (_journal.Pending().Any(p => p.JobId != productionJobId))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        var existing = await _session.GetProductionPackageAsync(productionJobId, cancellationToken).ConfigureAwait(false);
        if (existing is not null)
        {
            // A Core package is not proof that a different orphan GPU prompt has drained.
            foreach (var pending in _journal.Pending().Where(p => p.JobId == productionJobId))
                await ReconcileTerminalSubmissionAsync(pending, cancellationToken).ConfigureAwait(false);
            return existing;
        }
        // ── Check the entire immutable multi-shot plan BEFORE expensive model hash/preflight ──
        // ── and before claiming a lease. One unsafe late shot must not waste earlier GPU renders. ──
        var originalPlan = await _session.GetProductionPlanAsync(productionJobId, cancellationToken).ConfigureAwait(false);
        // A v1.1 candidate may not displace recovery of its own unknown previous
        // POST. The same-EXE Host's existing global recovery owns reconciliation;
        // until it drains, deny preflight/lease/all fresh GPU work here as well.
        if (originalPlan.SchemaVersion == "1.1"
            && ReferenceSnapshots is null
            && _journal.Pending().Any(p => p.JobId == productionJobId))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        ValidateMultiShotPlan(productionJobId, originalPlan, ReferenceSnapshots is not null);
        var preflight = await (_preflightOverride?.Invoke(cancellationToken) ?? PreflightAsync(cancellationToken)).ConfigureAwait(false);
        if (!preflight.IsReady)
        {
            throw new ProductionWorkerException("MEDIA_PREFLIGHT_FAILED");
        }
        var originalDigest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(originalPlan)!))).ToLowerInvariant();
        using var references = new DurableReferenceSnapshotBatch();
        if (originalPlan.SchemaVersion == "1.1")
        {
            var store = ReferenceSnapshots ?? throw new ProductionWorkerException("I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED");
            store.RequireInputRoot(preflight.InputRoot);
            // Validate/stage ALL I2V shots before any lease or earlier T2V POST. No second lock:
            // the existing journal GPU exclusion already covers GUI and same-EXE Worker.
            foreach (var task in originalPlan.Tasks.Where(t => t.RenderIntent == "IMAGE_TO_VIDEO"))
            {
                var relative = ProductionReferenceSnapshotStore.RelativePathFor(task, originalDigest);
                var graph = BuildPrompt(productionJobId, task, preflight, relative, requireInput: false);
                references.Add(task.ProductionTaskId, await store.PrepareAsync(originalPlan, task,
                    originalDigest, ProductionSubmissionJournal.GraphDigest(graph), _journal, cancellationToken).ConfigureAwait(false));
            }
        }
        // ── Preflight may be slow; recheck admission immediately before claiming Core lease. ──
        if (_acceptanceAdmission is not null
            && !await _acceptanceAdmission(productionJobId, cancellationToken).ConfigureAwait(false))
            throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD");
        ProductionClaimRecord claim;
        try
        {
            // ── 锁定当前授权至 claim 返回；切换 HOLD 不得产生新的 Core lease。 ──
            using var claimPermit = _submissionPermit?.Invoke(productionJobId, originalDigest);
            await references.ReauthorizeAsync(cancellationToken).ConfigureAwait(false);
            claim = await _session.ClaimProductionJobAsync(productionJobId, _executorId, cancellationToken).ConfigureAwait(false);
        }
        catch (ApiException error) when (error.StatusCode == 409)
        {
            // Current Core correctly refuses an expired *unbound* Running attempt. A legacy
            // worker may have POSTed it without a journal. Do not let that refusal admit job B.
            // Transport hides the precise conflict reason, so conservatively protect all not-yet-
            // settled executable graphs. This never invents a lease, attempt, failure or GPU POST.
            foreach (var task in originalPlan.Tasks.Where(t => t.ExecutionDisposition == "Executable" && t.WorkflowId is not null))
            {
                var known = _journal.Read(productionJobId, task.ProductionTaskId);
                if (known is not null && known.Phase != "Prepared") continue;
                var graphDigest = ProductionSubmissionJournal.GraphDigest(BuildPrompt(productionJobId, task, preflight,
                    references.Get(task.ProductionTaskId)?.RelativePath));
                _journal.Save(new(productionJobId, task.ProductionTaskId, originalDigest, graphDigest, "Submitting", known?.PromptId));
            }
            throw new ProductionWorkerException("MEDIA_CLAIM_CONFLICT_RECONCILIATION");
        }
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        Exception? leaseFailure = null;
        var heartbeat = KeepLeaseAsync();
        try
        {
            foreach (var snapshot in claim.Tasks.Where(t => t.Status == "Succeeded"))
            {
                var known = _journal.Read(productionJobId, snapshot.ProductionTaskId);
                if (known is not null) await ReconcileTerminalSubmissionAsync(known, lifetime.Token).ConfigureAwait(false);
                ObserveShot(new(productionJobId, snapshot.ProductionTaskId, snapshot.AttemptCount,
                    snapshot.ComfyPromptId is not null, 0, "REUSED_CORE_SUCCEEDED"));
            }
            foreach (var task in claim.Plan.Tasks.OrderBy(item => item.Order))
            {
                lifetime.Token.ThrowIfCancellationRequested();
                if (task.ExecutionDisposition != "Executable" || string.IsNullOrWhiteSpace(task.WorkflowId))
                    throw new ProductionWorkerException("PRODUCTION_PLAN_CONTAINS_NEEDS_HUMAN_TASK");
                if (!originalPlan.Tasks.Any(t => t == task)) throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
                var observed = claim.Tasks.Single(t => t.ProductionTaskId == task.ProductionTaskId);
                var persisted = _journal.Read(productionJobId, task.ProductionTaskId);
                var knownPrompt = observed.ComfyPromptId is not null || persisted?.PromptId is not null;
                var timer = System.Diagnostics.Stopwatch.StartNew();
                try
                {
                    await ExecuteTaskAsync(claim, task, originalDigest, preflight, lifetime.Token, references.Get(task.ProductionTaskId))
                        .ConfigureAwait(false);
                    ObserveShot(new(productionJobId, task.ProductionTaskId, observed.AttemptCount,
                        knownPrompt, timer.ElapsedMilliseconds, "CORE_COMMITTED"));
                }
                catch (Exception error)
                {
                    // ── Never turn an unknown transport outcome into a made-up GPU failure. ──
                    var code = error switch
                    {
                        ProductionWorkerException failure => failure.Code,
                        OperationCanceledException => "INTERRUPTED",
                        HttpRequestException => "TRANSPORT_UNCERTAIN",
                        _ => "EXECUTION_UNVERIFIED",
                    };
                    ObserveShot(new(productionJobId, task.ProductionTaskId, observed.AttemptCount,
                        knownPrompt, timer.ElapsedMilliseconds, code));
                    throw;
                }
            }
            return await _session.GetProductionPackageAsync(productionJobId, lifetime.Token).ConfigureAwait(false)
                ?? throw new ProductionWorkerException("PRODUCTION_PACKAGE_NOT_FINALIZED");
        }
        catch (OperationCanceledException) when (leaseFailure is not null && !cancellationToken.IsCancellationRequested)
        { throw new ProductionWorkerException("PRODUCTION_LEASE_LOST"); }
        finally { await lifetime.CancelAsync().ConfigureAwait(false); await heartbeat.ConfigureAwait(false); }

        async Task KeepLeaseAsync()
        {
            try
            {
                while (true)
                {
                    await Task.Delay(_heartbeatInterval, lifetime.Token).ConfigureAwait(false);
                    using var heartbeatTimeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                    heartbeatTimeout.CancelAfter(TimeSpan.FromSeconds(15));
                    await _session.HeartbeatProductionJobAsync(claim.ProductionJobId, _executorId, claim.LeaseToken, heartbeatTimeout.Token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            catch (Exception exception) { leaseFailure = exception; await lifetime.CancelAsync().ConfigureAwait(false); }
        }
    }

    // ── Telemetry never changes the Core lease, journal, GPU outcome or user workflow. ──
    private void ObserveShot(ProductionShotObservation record)
    {
        try { _shotObserver?.Invoke(record); }
        catch (Exception) { /* Metrics must never change production correctness. */ }
    }

    /// <summary>Only Core-authorized executable workflows may enter an automatic multi-shot run.</summary>
    private static void ValidateMultiShotPlan(string jobId, ProductionPlanRecord plan, bool hasDurableReferences)
    {
        if (plan.SchemaVersion == "1.1")
        {
            // Pending Journal reconciliation has priority (the Host runs its global
            // barrier first). This validation is BEFORE preflight/claim/any GPU POST.
            // Core's new v1.1 lease remains intentionally disabled until the
            // persistent Comfy LoadImage snapshot lifetime is actually enforced.
            ValidateV11FrozenReferenceIdentities(jobId, plan);
            if (!hasDurableReferences)
                throw new ProductionWorkerException("I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED");
            return;
        }
        // The frozen v1.0 Core plan transports only a local path, NOT an authenticated
        // SHA/byte/rights/source approval. Such an I2V task cannot be authorized for
        // a fresh GPU POST. Do not mint consent from a filename or silently use T2V.
        // This guard runs AFTER the journal's pending reconciliation barrier, but
        // BEFORE expensive model preflight, Core lease reservation or Comfy submission.
        if (plan.Tasks?.Any(t =>
            t.WorkflowId == ComfyWorkflowTemplateValidator.I2VWorkflowId
            || t.RenderIntent == "IMAGE_TO_VIDEO") == true)
            throw new ProductionWorkerException("I2V_REFERENCE_APPROVAL_CONTRACT_REQUIRED");

        if (plan.ProductionJobId != jobId
            || plan.SchemaVersion != "1.0"
            || plan.ProductionProfile != "production.comfyui.v1"
            || plan.Tasks is not { Length: > 0 }
            || plan.Tasks.Any(task =>
                task.ExecutionDisposition != "Executable"
                || task.WorkflowId is not (
                    ComfyWorkflowTemplateValidator.T2VWorkflowId
                    or ComfyWorkflowTemplateValidator.I2VWorkflowId))
            || plan.Tasks.Select(task => task.ProductionTaskId).Distinct(StringComparer.Ordinal).Count() != plan.Tasks.Length)
        {
            throw new ProductionWorkerException("PRODUCTION_PLAN_NOT_FULLY_EXECUTABLE");
        }
    }

    /// <summary>
    /// Read-only v1.1 snapshot admission guard. Never convert a SHA or local path into
    /// consent; that remains a fresh authenticated Core authorization plus Codex verifier.
    /// This preserves old v1.0 T2V and rejects untrusted v1.1 before Core lease/GPU.
    /// </summary>
    internal static void ValidateV11FrozenReferenceIdentities(string jobId, ProductionPlanRecord plan)
    {
        if (plan.ProductionJobId != jobId || plan.Tasks is not { Length: > 0 }
            || plan.ProductionProfile != "production.comfyui.v1"
            || plan.Tasks.Select(x => x.ProductionTaskId).Distinct(StringComparer.Ordinal).Count() != plan.Tasks.Length
            || plan.Tasks.Select(x => x.ShotId).Distinct(StringComparer.Ordinal).Count() != plan.Tasks.Length)
            throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var requiredI2V = 0;
        foreach (var task in plan.Tasks)
        {
            var reference = task.ReferenceAsset;
            if (task.RenderIntent == "GENERATIVE_VIDEO")
            {
                if (reference is not null || task.TrustedInputAssetRef is not null
                    || task.ExecutionDisposition != "Executable"
                    || task.WorkflowId != ComfyWorkflowTemplateValidator.T2VWorkflowId)
                    throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
                continue;
            }
            if (task.RenderIntent != "IMAGE_TO_VIDEO" || task.WorkflowId != ComfyWorkflowTemplateValidator.I2VWorkflowId
                || task.ExecutionDisposition != "Executable" || reference is null
                || reference.SchemaVersion != "reference_asset.v1"
                || reference.ProductionJobId != jobId || reference.ProductionTaskId != task.ProductionTaskId
                || reference.ShotId != task.ShotId
                || reference.CreativePackageId != plan.CreativePackageId
                || reference.CreativePackageDigest != plan.CreativePackageDigest
                || plan.ProjectKey != "goal-" + reference.GoalId
                || reference.RightsScope != "wan22.i2v.production.v1"
                || string.IsNullOrWhiteSpace(reference.ApprovalId)
                || string.IsNullOrWhiteSpace(reference.AssetId) || !ids.Add(reference.AssetId)
                || reference.Bytes is <= 0 or > 33554432
                || reference.Sha256.Length != 64
                || reference.Sha256.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f'))
                || reference.InputRelativePath != task.TrustedInputAssetRef)
                throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
            var pathParts = reference.InputRelativePath.Split('/');
            if (pathParts.Length != 4 || pathParts[0] != "PicotooPet" || pathParts[1] != "references"
                || pathParts[2] != reference.Sha256)
                throw new ProductionWorkerException("I2V_V11_SNAPSHOT_NOT_CONTENT_ADDRESSED");
            requiredI2V++;
        }
        if (requiredI2V == 0)
            throw new ProductionWorkerException("I2V_V11_REFERENCE_IDENTITY_INVALID");
    }

    private async Task ExecuteTaskAsync(ProductionClaimRecord claim, ProductionTaskPlanRecord task, string planDigest,
        ProductionPreflightSnapshot preflight, CancellationToken cancellationToken,
        DurableReferenceSnapshot? reference = null)
    {
        var snapshot = claim.Tasks.SingleOrDefault(t => t.ProductionTaskId == task.ProductionTaskId)
            ?? throw new ProductionWorkerException("PRODUCTION_TASK_SNAPSHOT_MISSING");
        if (snapshot.Status == "Succeeded") return;
        if (task.RenderIntent == "IMAGE_TO_VIDEO" && (reference is null || snapshot.AttemptCount > 2))
            throw new ProductionWorkerException("I2V_V11_CRASH_DURABLE_SNAPSHOT_REQUIRED");
        var prompt = BuildPrompt(claim.ProductionJobId, task, preflight, reference?.RelativePath);
        // Journal binds the full immutable plan digest, never the narrowed lease resume-plan digest.
        var graphDigest = ProductionSubmissionJournal.GraphDigest(prompt);
        var state = _journal.Read(claim.ProductionJobId, task.ProductionTaskId);
        if (state is not null && (state.PlanDigest != planDigest || state.GraphDigest != graphDigest))
            throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
        var promptId = state?.PromptId ?? snapshot.ComfyPromptId;
        if (state?.PromptId is not null && snapshot.ComfyPromptId is not null && state.PromptId != snapshot.ComfyPromptId)
            throw new ProductionWorkerException("MEDIA_PROMPT_ID_CONFLICT");
        state ??= new ProductionSubmission(claim.ProductionJobId, task.ProductionTaskId, planDigest, graphDigest, "Prepared", promptId);
        if (state.Phase == "Settled") throw new ProductionWorkerException("MEDIA_CORE_RESULT_CONFLICT");

        // Opt-in reboot recovery for a single explicitly approved third shot.
        // No approval file => unchanged behavior: resume only the original prompt.
        // Core task.updated_at is the durable pre-boot binding witness; local
        // journal mtime is unsuitable because a reconnect may rewrite it.
        if (state.Phase == "Submitted" && state.PromptId is not null
            && snapshot.Status == "Running" && snapshot.AttemptCount == 1
            && snapshot.ComfyPromptId == state.PromptId
            && task.Order == 3 && claim.Tasks.Length == 3
            && claim.Tasks.Count(t => t.Status == "Succeeded") == 2
            && P0LostPromptRetryApproval.IsApproved(
                claim.ProductionJobId, task.ProductionTaskId, state.PromptId,
                planDigest, snapshot.UpdatedAt,
                P0LostPromptRetryApproval.CurrentWindowsBootUtc(), DateTimeOffset.UtcNow))
        {
            await AssertLostPromptNoGpuAndNoOutputAsync(
                claim.ProductionJobId, task, state.PromptId, preflight, cancellationToken)
                .ConfigureAwait(false);
            // Durable before Core modifies attempt1 / creates unbound attempt2.
            state = state with
            {
                Phase = "RetryPrepared",
                PreviousPromptId = state.PromptId,
                PreviousTaskUpdatedAtUtc = snapshot.UpdatedAt,
                PromptId = null,
            };
            _journal.Save(state);
            promptId = null;
        }

        if (state.Phase == "FailurePending")
        {
            await ReportFinalFailureAsync(claim, task, state, cancellationToken).ConfigureAwait(false);
            throw new ProductionWorkerException("COMFY_RETRY_BUDGET_EXHAUSTED");
        }
        if (state.Phase == "RetryPrepared")
        {
            // Approval persists across a crash AFTER reserving attempt2 but BEFORE
            // submitting. In this phase no new POST has started.
            var originalPrompt = state.PreviousPromptId
                ?? throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");
            var previousUpdatedUtc = state.PreviousTaskUpdatedAtUtc
                ?? throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");
            if (task.Order != 3 || claim.Tasks.Length != 3
                || claim.Tasks.Count(t => t.Status == "Succeeded") != 2
                || snapshot.Status != "Running"
                || !(snapshot.AttemptCount == 1 && snapshot.ComfyPromptId == originalPrompt
                    || snapshot.AttemptCount == 2 && snapshot.ComfyPromptId is null)
                || !P0LostPromptRetryApproval.IsApproved(
                    claim.ProductionJobId, task.ProductionTaskId, originalPrompt,
                    planDigest, previousUpdatedUtc,
                    P0LostPromptRetryApproval.CurrentWindowsBootUtc(), DateTimeOffset.UtcNow))
                throw new ProductionWorkerException("MEDIA_RECOVERY_APPROVAL_INVALID");

            await AssertLostPromptNoGpuAndNoOutputAsync(
                claim.ProductionJobId, task, originalPrompt, preflight, cancellationToken)
                .ConfigureAwait(false);
            using var attempt2Permit = _submissionPermit?.Invoke(claim.ProductionJobId, planDigest);
            if (reference is not null) await reference.ReauthorizeAsync(cancellationToken).ConfigureAwait(false);
            // Core replays null reservation idempotently if attempt2 was already
            // reserved before a crash. Attempt1 remains in Core audit.
            var reserved = await _session.MarkProductionAttemptAsync(
                claim.ProductionJobId, task.ProductionTaskId,
                new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null),
                cancellationToken).ConfigureAwait(false);
            if (reserved.AttemptCount != 2 || reserved.Status != "Running"
                || reserved.ComfyPromptId is not null)
                throw new ProductionWorkerException("MEDIA_ATTEMPT2_RESERVATION_CONFLICT");
            // Crash after this transition is uncertain: reconciler must find
            // attempt2 graph before any further POST, even if history is missing.
            state = state with { Phase = "Submitting" };
            _journal.Save(state);
            if (reference is not null) await reference.ReauthorizeAsync(cancellationToken).ConfigureAwait(false);
            promptId = await _comfy.SubmitPromptAsync(prompt, cancellationToken)
                .ConfigureAwait(false);
        }
        else if (promptId is null && (state.Phase is "Submitting" or "Submitted" || snapshot.AttemptCount > 0))
        {
            // Legacy unbound attempts AND crash after reservation are uncertain, even if Prepared.
            // Persist the GPU barrier before any network read that can fail or return no match.
            state = state with { Phase = "Submitting" }; _journal.Save(state);
            promptId = await _reconciler.FindExactAsync(graphDigest, cancellationToken).ConfigureAwait(false)
                ?? throw new ProductionWorkerException("MEDIA_SUBMISSION_UNKNOWN");
            if (state.PreviousPromptId is not null && promptId == state.PreviousPromptId)
                throw new ProductionWorkerException("MEDIA_SUBMISSION_UNKNOWN");
        }
        if (promptId is null)
        {
            // ── Opt-in acceptance gate holds the exact authorization file through the new POST. ──
            // ── No permit means ordinary unattended mode; a denied permit changes no attempt. ──
            using var permit = _submissionPermit?.Invoke(claim.ProductionJobId, planDigest);
            if (reference is not null) await reference.ReauthorizeAsync(cancellationToken).ConfigureAwait(false);
            // Write intent first. An uncertain reservation is safe to replay, an uncertain POST is not.
            _journal.Save(state);
            await _session.MarkProductionAttemptAsync(claim.ProductionJobId, task.ProductionTaskId,
                new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null), cancellationToken).ConfigureAwait(false);
            state = state with { Phase = "Submitting" }; _journal.Save(state);
            if (reference is not null) await reference.ReauthorizeAsync(cancellationToken).ConfigureAwait(false);
            promptId = await _comfy.SubmitPromptAsync(prompt, cancellationToken).ConfigureAwait(false);
        }
        state = state with { PromptId = promptId, Phase = "Submitted" }; _journal.Save(state);
        await _session.MarkProductionAttemptAsync(claim.ProductionJobId, task.ProductionTaskId,
            new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, promptId), cancellationToken).ConfigureAwait(false);
        // No GPU retry on HTTP timeout/cancel. Restart/reconnect must reconcile this exact identity.
        ComfyOutputEvidence historyOutput;
        string relativeOutput, sha256;
        FileInfo file;
        var completedHistory = false;
        try
        {
            historyOutput = await WaitForOutputAsync(promptId, cancellationToken).ConfigureAwait(false);
            completedHistory = true;
            relativeOutput = BuildRelativeOutput(historyOutput.Subfolder, historyOutput.Filename);
            var outputPath = ResolveUnderRoot(preflight.OutputRoot!, relativeOutput, requireExistingFile: true);
            AssertNoLinkEscape(preflight.OutputRoot!, outputPath);
            file = new FileInfo(outputPath);
            if (file.Length <= 0) throw new ProductionWorkerException("COMFY_OUTPUT_EMPTY");
            sha256 = await Sha256FileAsync(outputPath, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception error) when (completedHistory && error is (IOException or InvalidDataException or UnauthorizedAccessException)
            // Missing Comfy history after restart (or a still-running prompt at timeout)
            // is uncertainty, not an observed terminal GPU failure. Preserve the
            // bound prompt and Core attempt; never invent a failure or second POST.
            || error is ProductionWorkerException worker && worker.Code is "COMFY_EXECUTION_FAILED" or "COMFY_OUTPUT_EMPTY" or "COMFY_OUTPUT_MISSING")
        {
            // Only definite bound-prompt failure. Unknown POST, HTTP uncertainty and cancellation
            // never enter this path and never authorize another GPU submission.
            await ReportFinalFailureAsync(claim, task, state, cancellationToken).ConfigureAwait(false);
            throw new ProductionWorkerException("COMFY_RETRY_BUDGET_EXHAUSTED");
        }
        await _session.CommitProductionResultAsync(claim.ProductionJobId, task.ProductionTaskId,
            new ProductionTaskCommitRequest(_executorId, claim.LeaseToken, promptId,
                relativeOutput.Replace('\\', '/'), sha256, file.Length, "video/webm",
                task.Width, task.Height, task.FrameCount, task.Fps), cancellationToken).ConfigureAwait(false);
        _journal.Save(state with { Phase = "Settled" });
    }

    private async Task ReportFinalFailureAsync(ProductionClaimRecord claim, ProductionTaskPlanRecord task,
        ProductionSubmission state, CancellationToken ct)
    {
        state = state with { Phase = "FailurePending", FailureCode = "COMFY_RETRY_BUDGET_EXHAUSTED" };
        _journal.Save(state);
        await _session.FailProductionTaskAsync(claim.ProductionJobId, task.ProductionTaskId,
            new ProductionTaskFailureRequest(_executorId, claim.LeaseToken, state.PromptId,
                "COMFY_RETRY_BUDGET_EXHAUSTED", null), ct).ConfigureAwait(false);
        // A timed-out prompt may still be on GPU. Core failure alone must not free the GPU barrier.
        if (await _reconciler.IsFinishedAsync(state.PromptId!, ct).ConfigureAwait(false))
            _journal.Save(state with { Phase = "Settled" });
    }

    private Task ReconcileTerminalSubmissionAsync(ProductionSubmission state, CancellationToken ct) =>
        ProductionPendingRecovery.ReconcileTerminalAsync(_journal, _reconciler, state, ct);

    /// <summary>No destructive Comfy actions; exclude active GPU and any already produced output.</summary>
    private async Task AssertLostPromptNoGpuAndNoOutputAsync(
        string jobId, ProductionTaskPlanRecord task, string oldPromptId,
        ProductionPreflightSnapshot preflight, CancellationToken ct)
    {
        if (_reconciler is not ComfyPromptReconciler readOnly
            || !await readOnly.IsMissingWithIdleQueueAsync(oldPromptId, ct).ConfigureAwait(false))
            throw new ProductionWorkerException("MEDIA_RECOVERY_GPU_UNVERIFIED");

        var prefix = BuildFilenamePrefix(jobId, task).Replace('/', Path.DirectorySeparatorChar);
        var outputPrefix = Path.Combine(preflight.OutputRoot!,
            Path.ChangeExtension(prefix, null) ?? prefix);
        var dir = Path.GetDirectoryName(outputPrefix)!;
        AssertNoLinkEscape(preflight.OutputRoot!, dir);
        if (Directory.Exists(dir) && Directory.EnumerateFiles(dir,
                Path.GetFileName(outputPrefix) + "*.webm", SearchOption.TopDirectoryOnly).Any())
            throw new ProductionWorkerException("MEDIA_RECOVERY_OUTPUT_EXISTS");
    }

    private static JsonObject BuildPrompt(string jobId, ProductionTaskPlanRecord task, ProductionPreflightSnapshot preflight,
        string? durableInput = null, bool requireInput = true)
    {
        var template = ComfyWorkflowCatalog.Load(task.WorkflowId!);
        string? trustedInput = task.WorkflowId == ComfyWorkflowTemplateValidator.I2VWorkflowId
            ? durableInput is not null && !requireInput ? durableInput
                : ValidateTrustedInput(durableInput ?? task.TrustedInputAssetRef, preflight.InputRoot!) : null;
        return ComfyWorkflowTemplateValidator.Bind(task.WorkflowId!, template, task, BuildFilenamePrefix(jobId, task), trustedInput);
    }

    private async Task<ComfyOutputEvidence> WaitForOutputAsync(string promptId, CancellationToken cancellationToken)
    {
        var timer = System.Diagnostics.Stopwatch.StartNew();
        while (timer.Elapsed < _historyTimeout)
        {
            var history = await _comfy.GetHistoryAsync(promptId, cancellationToken).ConfigureAwait(false);
            if (IsHistoryError(history, promptId))
                throw new ProductionWorkerException("COMFY_EXECUTION_FAILED");
            if (history[promptId]?["status"]?["completed"]?.GetValue<bool>() == true)
            {
                if (TryExtractOutput(history, promptId, out var output)) return output;
                throw new ProductionWorkerException("COMFY_OUTPUT_MISSING");
            }
            await Task.Delay(_pollInterval, cancellationToken).ConfigureAwait(false);
        }
        throw new ProductionWorkerException("COMFY_HISTORY_TIMEOUT");
    }

    private static bool TryExtractOutput(
        JsonObject history,
        string promptId,
        out ComfyOutputEvidence evidence)
    {
        evidence = default!;
        if (history[promptId] is not JsonObject entry
            || entry["outputs"] is not JsonObject outputs)
        {
            return false;
        }
        foreach (var outputNode in outputs)
        {
            if (outputNode.Value is not JsonObject node)
            {
                continue;
            }
            foreach (var value in node)
            {
                if (value.Value is not JsonArray array)
                {
                    continue;
                }
                foreach (var item in array.OfType<JsonObject>())
                {
                    var filename = item["filename"]?.GetValue<string>();
                    var type = item["type"]?.GetValue<string>();
                    if (string.IsNullOrWhiteSpace(filename)
                        || !filename.EndsWith(".webm", StringComparison.OrdinalIgnoreCase)
                        || !string.Equals(type, "output", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    evidence = new ComfyOutputEvidence(
                        filename,
                        item["subfolder"]?.GetValue<string>() ?? string.Empty);
                    return true;
                }
            }
        }
        return false;
    }

    private static bool IsHistoryError(JsonObject history, string promptId)
    {
        if (history[promptId] is not JsonObject entry
            || entry["status"] is not JsonObject status)
        {
            return false;
        }
        var statusText = status["status_str"]?.GetValue<string>();
        return string.Equals(statusText, "error", StringComparison.OrdinalIgnoreCase);
    }

    private static string ResolveComfyDataRoot() =>
        ProductionLocalEnvironment.ResolveComfyDataRoot();

    private static string ValidateTrustedInput(string? relative, string inputRoot)
    {
        if (string.IsNullOrWhiteSpace(relative))
        {
            throw new InvalidDataException("COMFY_I2V_INPUT_MISSING");
        }
        var path = ResolveUnderRoot(inputRoot, relative, requireExistingFile: true);
        AssertNoLinkEscape(inputRoot, path);
        return Path.GetRelativePath(inputRoot, path).Replace('\\', '/');
    }

    private static string BuildFilenamePrefix(string jobId, ProductionTaskPlanRecord task)
    {
        var safeShot = new string(task.ShotId
            .Select(character => char.IsLetterOrDigit(character) || character is '-' or '_' ? character : '-')
            .ToArray());
        return $"PicotooPet/production/{jobId}/{task.Order:D3}-{safeShot}";
    }

    private static string BuildRelativeOutput(string subfolder, string filename)
    {
        if (string.IsNullOrWhiteSpace(filename)
            || Path.IsPathRooted(filename)
            || filename.Contains("..", StringComparison.Ordinal))
        {
            throw new InvalidDataException("COMFY_OUTPUT_FILENAME_INVALID");
        }
        if (string.IsNullOrWhiteSpace(subfolder))
        {
            return filename;
        }
        if (Path.IsPathRooted(subfolder) || subfolder.Contains("..", StringComparison.Ordinal))
        {
            throw new InvalidDataException("COMFY_OUTPUT_SUBFOLDER_INVALID");
        }
        return Path.Combine(subfolder, filename);
    }

    private static string ResolveUnderRoot(
        string root,
        string relative,
        bool requireExistingFile) =>
        ProductionLocalEnvironment.ResolveUnderRoot(root, relative, requireExistingFile);

    private static void AssertNoLinkEscape(string root, string path) =>
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path);

    private static async Task<string> Sha256FileAsync(
        string path,
        CancellationToken cancellationToken) =>
        await ProductionLocalEnvironment.Sha256FileAsync(path, cancellationToken).ConfigureAwait(false);

    internal static string NormalizeExecutorId(string value)
    {
        // Mac Core ProductionClaimRequest requires ASCII [A-Za-z0-9_.-].
        // Windows machine names may contain Chinese or other Unicode letters.
        var normalized = new string(value
            .Select(character => char.IsAsciiLetterOrDigit(character) || character is '_' or '-' or '.'
                ? character
                : '-')
            .Take(120)
            .ToArray());
        return string.IsNullOrWhiteSpace(normalized) ? "windows-production" : normalized;
    }

    public async ValueTask DisposeAsync()
    {
        if (_reconciler is IDisposable disposable) disposable.Dispose();
        if (_ownsComfy)
        {
            await _comfy.DisposeAsync().ConfigureAwait(false);
        }
    }

    private sealed class SessionGateway(ControlCenterSession session) : IProductionExecutionGateway
    {
        public Task<ProductionPlanRecord> GetProductionPlanAsync(string j, CancellationToken ct) => session.GetProductionPlanAsync(j, ct);
        public Task<ProductionClaimRecord> ClaimProductionJobAsync(string j, string e, CancellationToken ct) => session.ClaimProductionJobAsync(j, e, ct);
        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(string j, string e, string l, CancellationToken ct) => session.HeartbeatProductionJobAsync(j, e, l, ct);
        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(string j, string t, ProductionTaskAttemptRequest r, CancellationToken ct) => session.MarkProductionAttemptAsync(j, t, r, ct);
        public Task<ProductionTaskRecord> CommitProductionResultAsync(string j, string t, ProductionTaskCommitRequest r, CancellationToken ct) => session.CommitProductionResultAsync(j, t, r, ct);
        public Task<ProductionTaskRecord> FailProductionTaskAsync(string j, string t, ProductionTaskFailureRequest r, CancellationToken ct) => session.FailProductionTaskAsync(j, t, r, ct);
        public Task<ProductionPackageRecord?> GetProductionPackageAsync(string j, CancellationToken ct) => session.GetProductionPackageAsync(j, ct);
    }

    private sealed record ComfyOutputEvidence(string Filename, string Subfolder);
}

/// <summary>只读 preflight 快照；不给 UI 暴露可编辑 renderer 参数。</summary>
public sealed record ProductionPreflightSnapshot(
    bool IsReady,
    string Detail,
    string? DataRoot,
    string? InputRoot,
    string? OutputRoot,
    string? ModelRoot,
    IReadOnlyList<string> Checks)
{
    public static ProductionPreflightSnapshot Failed(string detail, IReadOnlyList<string> checks) =>
        new(false, detail, null, null, null, null, checks.ToArray());
}
