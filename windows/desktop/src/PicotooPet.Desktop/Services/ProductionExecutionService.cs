using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Runtime.CompilerServices;

[assembly: InternalsVisibleTo("PicotooPet.MediaWorker.SmokeTests")]
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

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
    private readonly ComfyProductionClient _comfy;
    private readonly bool _ownsComfy;
    private readonly string _executorId;

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
    }

    private ProductionExecutionService(
        ControlCenterSession session,
        ComfyProductionClient comfy,
        string executorId,
        bool ownsComfy)
    {
        _session = new SessionGateway(session);
        _journal = new(ProductionSubmissionJournal.DefaultRoot);
        _reconciler = ComfyPromptReconciler.Create();
        _comfy = comfy;
        _executorId = executorId;
        _ownsComfy = ownsComfy;
    }

    /// <summary>同一 executor 的独立用户进程组合；不创建 WPF 会话。</summary>
    public ProductionExecutionService(IProductionExecutionGateway gateway, ComfyProductionClient comfy)
        : this(gateway, comfy, new(ProductionSubmissionJournal.DefaultRoot), ComfyPromptReconciler.Create(), null) { }

    internal ProductionExecutionService(IProductionExecutionGateway gateway, ComfyProductionClient comfy,
        ProductionSubmissionJournal journal, IComfyPromptReconciler reconciler,
        Func<CancellationToken, Task<ProductionPreflightSnapshot>>? preflight,
        TimeSpan? pollInterval = null, TimeSpan? heartbeatInterval = null)
    {
        _session = gateway; _comfy = comfy; _journal = journal; _reconciler = reconciler;
        _preflightOverride = preflight;
        _executorId = NormalizeExecutorId($"windows-production-{Environment.MachineName}");
        _pollInterval = pollInterval ?? TimeSpan.FromSeconds(2);
        _heartbeatInterval = heartbeatInterval ?? TimeSpan.FromSeconds(30);
    }

    /// <summary>创建正式固定 loopback executor；没有 endpoint 参数。</summary>
    public static ProductionExecutionService Create(ControlCenterSession session) =>
        new(
            session,
            ComfyProductionClient.Create(),
            NormalizeExecutorId($"windows-production-{Environment.MachineName}"),
            ownsComfy: true);

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
        using var gpu = _journal.AcquireGpu();
        // A process death releases the lock, not the submission uncertainty of a prior GPU job.
        if (_journal.Pending().Any(p => p.JobId != productionJobId))
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        var preflight = await (_preflightOverride?.Invoke(cancellationToken) ?? PreflightAsync(cancellationToken)).ConfigureAwait(false);
        if (!preflight.IsReady)
        {
            throw new InvalidOperationException($"PRODUCTION_PREFLIGHT_FAILED:{preflight.Detail}");
        }

        var originalPlan = await _session.GetProductionPlanAsync(productionJobId, cancellationToken).ConfigureAwait(false);
        var originalDigest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(originalPlan)!))).ToLowerInvariant();
        var claim = await _session.ClaimProductionJobAsync(
            productionJobId,
            _executorId,
            cancellationToken).ConfigureAwait(false);
        using var lifetime = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        Exception? leaseFailure = null;
        var heartbeat = KeepLeaseAsync();
        try
        {
            foreach (var snapshot in claim.Tasks.Where(t => t.Status == "Succeeded"))
            {
                var known = _journal.Read(productionJobId, snapshot.ProductionTaskId);
                if (known is not null) _journal.Save(known with { Phase = "Settled" });
            }
            foreach (var task in claim.Plan.Tasks.OrderBy(item => item.Order))
            {
                lifetime.Token.ThrowIfCancellationRequested();
                if (task.ExecutionDisposition != "Executable" || string.IsNullOrWhiteSpace(task.WorkflowId))
                    throw new ProductionWorkerException("PRODUCTION_PLAN_CONTAINS_NEEDS_HUMAN_TASK");
                if (!originalPlan.Tasks.Any(t => t == task)) throw new ProductionWorkerException("MEDIA_SUBMISSION_IDENTITY_CONFLICT");
                await ExecuteTaskAsync(claim, task, originalDigest, preflight, lifetime.Token).ConfigureAwait(false);
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
                    await _session.HeartbeatProductionJobAsync(claim.ProductionJobId, _executorId, claim.LeaseToken, lifetime.Token).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException) when (lifetime.IsCancellationRequested) { }
            catch (Exception exception) { leaseFailure = exception; await lifetime.CancelAsync().ConfigureAwait(false); }
        }
    }

    private async Task ExecuteTaskAsync(ProductionClaimRecord claim, ProductionTaskPlanRecord task, string planDigest,
        ProductionPreflightSnapshot preflight, CancellationToken cancellationToken)
    {
        var snapshot = claim.Tasks.SingleOrDefault(t => t.ProductionTaskId == task.ProductionTaskId)
            ?? throw new ProductionWorkerException("PRODUCTION_TASK_SNAPSHOT_MISSING");
        if (snapshot.Status == "Succeeded") return;
        var template = ComfyWorkflowCatalog.Load(task.WorkflowId!);
        string? trustedInput = task.WorkflowId == ComfyWorkflowTemplateValidator.I2VWorkflowId
            ? ValidateTrustedInput(task.TrustedInputAssetRef, preflight.InputRoot!) : null;
        var prompt = ComfyWorkflowTemplateValidator.Bind(task.WorkflowId!, template, task,
            BuildFilenamePrefix(claim.ProductionJobId, task), trustedInput);
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
        if (promptId is null && (state.Phase is "Submitting" or "Submitted" || snapshot.AttemptCount > 0 && _journal.Read(claim.ProductionJobId, task.ProductionTaskId) is null))
        {
            promptId = await _reconciler.FindExactAsync(graphDigest, cancellationToken).ConfigureAwait(false)
                ?? throw new ProductionWorkerException("MEDIA_SUBMISSION_UNKNOWN");
        }
        if (promptId is null)
        {
            // Write intent first. An uncertain reservation is safe to replay, an uncertain POST is not.
            _journal.Save(state);
            await _session.MarkProductionAttemptAsync(claim.ProductionJobId, task.ProductionTaskId,
                new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null), cancellationToken).ConfigureAwait(false);
            state = state with { Phase = "Submitting" }; _journal.Save(state);
            promptId = await _comfy.SubmitPromptAsync(prompt, cancellationToken).ConfigureAwait(false);
        }
        state = state with { PromptId = promptId, Phase = "Submitted" }; _journal.Save(state);
        await _session.MarkProductionAttemptAsync(claim.ProductionJobId, task.ProductionTaskId,
            new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, promptId), cancellationToken).ConfigureAwait(false);
        // No GPU retry on HTTP timeout/cancel. Restart/reconnect must reconcile this exact identity.
        var historyOutput = await WaitForOutputAsync(claim, task, promptId, cancellationToken).ConfigureAwait(false);
        var relativeOutput = BuildRelativeOutput(historyOutput.Subfolder, historyOutput.Filename);
        var outputPath = ResolveUnderRoot(preflight.OutputRoot!, relativeOutput, requireExistingFile: true);
        AssertNoLinkEscape(preflight.OutputRoot!, outputPath);
        var file = new FileInfo(outputPath);
        if (file.Length <= 0) throw new ProductionWorkerException("COMFY_OUTPUT_EMPTY");
        var sha256 = await Sha256FileAsync(outputPath, cancellationToken).ConfigureAwait(false);
        await _session.CommitProductionResultAsync(claim.ProductionJobId, task.ProductionTaskId,
            new ProductionTaskCommitRequest(_executorId, claim.LeaseToken, promptId,
                relativeOutput.Replace('\\', '/'), sha256, file.Length, "video/webm",
                task.Width, task.Height, task.FrameCount, task.Fps), cancellationToken).ConfigureAwait(false);
        _journal.Save(state with { Phase = "Settled" });
    }

    private async Task<ComfyOutputEvidence> WaitForOutputAsync(ProductionClaimRecord claim,
        ProductionTaskPlanRecord task, string promptId, CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + TimeSpan.FromMinutes(20);
        while (DateTimeOffset.UtcNow < deadline)
        {
            var history = await _comfy.GetHistoryAsync(promptId, cancellationToken).ConfigureAwait(false);
            if (IsHistoryError(history, promptId))
            {
                await _session.FailProductionTaskAsync(claim.ProductionJobId, task.ProductionTaskId,
                    new ProductionTaskFailureRequest(_executorId, claim.LeaseToken, promptId, "COMFY_EXECUTION_FAILED", null),
                    cancellationToken).ConfigureAwait(false);
                var state = _journal.Read(claim.ProductionJobId, task.ProductionTaskId);
                if (state is not null) _journal.Save(state with { Phase = "Settled" });
                throw new ProductionWorkerException("COMFY_EXECUTION_FAILED");
            }
            if (TryExtractOutput(history, promptId, out var output)) return output;
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

    private static string NormalizeExecutorId(string value)
    {
        var normalized = new string(value
            .Select(character => char.IsLetterOrDigit(character) || character is '_' or '-' or '.'
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
