using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>2.3.20.1 Windows 本地 GPU executor；只执行 Core 已冻结的 Production Plan。</summary>
public sealed class ProductionExecutionService : IAsyncDisposable
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

    private readonly ControlCenterSession _session;
    private readonly ComfyProductionClient _comfy;
    private readonly bool _ownsComfy;
    private readonly string _executorId;

    public ProductionExecutionService(
        ControlCenterSession session,
        ComfyProductionClient comfy,
        string? executorId = null)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
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
        _session = session;
        _comfy = comfy;
        _executorId = executorId;
        _ownsComfy = ownsComfy;
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
        if (IsDesktopResourceTree(dataRoot))
        {
            return ProductionPreflightSnapshot.Failed(
                "Comfy Desktop resources\\ComfyUI 属于只读程序资源，不能作为生产数据根。",
                checks);
        }
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
        var preflight = await PreflightAsync(cancellationToken).ConfigureAwait(false);
        if (!preflight.IsReady)
        {
            throw new InvalidOperationException($"PRODUCTION_PREFLIGHT_FAILED:{preflight.Detail}");
        }

        var claim = await _session.ClaimProductionJobAsync(
            productionJobId,
            _executorId,
            cancellationToken).ConfigureAwait(false);
        foreach (var task in claim.Plan.Tasks.OrderBy(item => item.Order))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!string.Equals(task.ExecutionDisposition, "Executable", StringComparison.Ordinal))
            {
                throw new InvalidOperationException("PRODUCTION_PLAN_CONTAINS_NEEDS_HUMAN_TASK");
            }
            if (string.IsNullOrWhiteSpace(task.WorkflowId))
            {
                throw new InvalidOperationException("PRODUCTION_PLAN_WORKFLOW_MISSING");
            }
            await ExecuteTaskAsync(
                claim,
                task,
                preflight,
                cancellationToken).ConfigureAwait(false);
        }

        var package = await _session.GetProductionPackageAsync(
            productionJobId,
            cancellationToken).ConfigureAwait(false);
        return package ?? throw new InvalidOperationException("PRODUCTION_PACKAGE_NOT_FINALIZED");
    }

    private async Task ExecuteTaskAsync(
        ProductionClaimRecord claim,
        ProductionTaskPlanRecord task,
        ProductionPreflightSnapshot preflight,
        CancellationToken cancellationToken)
    {
        Exception? lastRetryable = null;
        for (var attempt = 1; attempt <= 2; attempt++)
        {
            try
            {
                var template = ComfyWorkflowCatalog.Load(task.WorkflowId!);
                var filenamePrefix = BuildFilenamePrefix(claim.ProductionJobId, task);
                string? trustedInput = null;
                if (string.Equals(
                    task.WorkflowId,
                    ComfyWorkflowTemplateValidator.I2VWorkflowId,
                    StringComparison.Ordinal))
                {
                    trustedInput = ValidateTrustedInput(task.TrustedInputAssetRef, preflight.InputRoot!);
                }
                var prompt = ComfyWorkflowTemplateValidator.Bind(
                    task.WorkflowId!,
                    template,
                    task,
                    filenamePrefix,
                    trustedInput);

                // ── Core 必须先预留 attempt，GPU submit 才允许发生；避免孤儿任务 ──────
                await _session.MarkProductionAttemptAsync(
                    claim.ProductionJobId,
                    task.ProductionTaskId,
                    new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, null),
                    cancellationToken).ConfigureAwait(false);
                var promptId = await _comfy.SubmitPromptAsync(prompt, cancellationToken)
                    .ConfigureAwait(false);

                // ── prompt_id 只绑定刚才的 reservation，不消耗第二次 attempt ──────────
                await _session.MarkProductionAttemptAsync(
                    claim.ProductionJobId,
                    task.ProductionTaskId,
                    new ProductionTaskAttemptRequest(_executorId, claim.LeaseToken, promptId),
                    cancellationToken).ConfigureAwait(false);

                var historyOutput = await WaitForOutputAsync(
                    claim,
                    promptId,
                    cancellationToken).ConfigureAwait(false);
                var relativeOutput = BuildRelativeOutput(historyOutput.Subfolder, historyOutput.Filename);
                var outputPath = ResolveUnderRoot(
                    preflight.OutputRoot!,
                    relativeOutput,
                    requireExistingFile: true);
                AssertNoLinkEscape(preflight.OutputRoot!, outputPath);
                var file = new FileInfo(outputPath);
                if (file.Length <= 0)
                {
                    throw new InvalidDataException("COMFY_OUTPUT_EMPTY");
                }
                var sha256 = await Sha256FileAsync(outputPath, cancellationToken).ConfigureAwait(false);
                await _session.CommitProductionResultAsync(
                    claim.ProductionJobId,
                    task.ProductionTaskId,
                    new ProductionTaskCommitRequest(
                        _executorId,
                        claim.LeaseToken,
                        promptId,
                        relativeOutput.Replace('\\', '/'),
                        sha256,
                        file.Length,
                        "video/webm",
                        task.Width,
                        task.Height,
                        task.FrameCount,
                        task.Fps),
                    cancellationToken).ConfigureAwait(false);
                return;
            }
            catch (Exception exception) when (IsRetryable(exception, cancellationToken) && attempt < 2)
            {
                lastRetryable = exception;
                await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
            }
        }
        throw new InvalidOperationException("COMFY_RETRY_BUDGET_EXHAUSTED", lastRetryable);
    }

    private async Task<ComfyOutputEvidence> WaitForOutputAsync(
        ProductionClaimRecord claim,
        string promptId,
        CancellationToken cancellationToken)
    {
        var deadline = DateTimeOffset.UtcNow + TimeSpan.FromMinutes(20);
        var nextHeartbeat = DateTimeOffset.UtcNow + TimeSpan.FromSeconds(45);
        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (DateTimeOffset.UtcNow >= nextHeartbeat)
            {
                await _session.HeartbeatProductionJobAsync(
                    claim.ProductionJobId,
                    _executorId,
                    claim.LeaseToken,
                    cancellationToken).ConfigureAwait(false);
                nextHeartbeat = DateTimeOffset.UtcNow + TimeSpan.FromSeconds(45);
            }

            var history = await _comfy.GetHistoryAsync(promptId, cancellationToken).ConfigureAwait(false);
            if (TryExtractOutput(history, promptId, out var output))
            {
                return output;
            }
            if (IsHistoryError(history, promptId))
            {
                throw new InvalidDataException("COMFY_EXECUTION_FAILED");
            }
            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken).ConfigureAwait(false);
        }
        throw new TimeoutException("COMFY_HISTORY_TIMEOUT");
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

    private static string ResolveComfyDataRoot()
    {
        var candidates = new List<string>();
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var configPath = Path.Combine(appData, "ComfyUI", "config.json");
        if (File.Exists(configPath))
        {
            try
            {
                using var config = JsonDocument.Parse(File.ReadAllText(configPath));
                if (config.RootElement.TryGetProperty("basePath", out var basePath)
                    && basePath.ValueKind == JsonValueKind.String
                    && !string.IsNullOrWhiteSpace(basePath.GetString()))
                {
                    candidates.Add(basePath.GetString()!);
                }
            }
            catch (JsonException)
            {
                // ── 损坏 config 不会扩大候选范围，只继续检查固定安全候选 ───────────
            }
        }
        candidates.AddRange(
        [
            Path.Combine(appData, "ComfyUI"),
            Path.Combine(localAppData, "ComfyUI"),
            Path.Combine(userProfile, "ComfyUI"),
            @"D:\ComfyUI",
            @"D:\PicotooPet\ComfyUI",
            @"E:\ComfyUI",
        ]);

        foreach (var candidate in candidates.Where(item => !string.IsNullOrWhiteSpace(item)))
        {
            var full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(candidate));
            if (!Directory.Exists(full) || IsDesktopResourceTree(full))
            {
                continue;
            }
            if (Directory.Exists(Path.Combine(full, "models"))
                || Directory.Exists(Path.Combine(full, "custom_nodes"))
                || File.Exists(Path.Combine(full, "main.py"))
                || Directory.Exists(Path.Combine(full, "output")))
            {
                return full;
            }
        }
        throw new DirectoryNotFoundException("COMFY_DATA_ROOT_NOT_FOUND");
    }

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
        bool requireExistingFile)
    {
        if (Path.IsPathRooted(relative))
        {
            throw new InvalidDataException("PRODUCTION_PATH_MUST_BE_RELATIVE");
        }
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(Path.Combine(fullRoot, relative));
        if (!full.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("PRODUCTION_PATH_ESCAPE");
        }
        if (requireExistingFile && !File.Exists(full))
        {
            throw new FileNotFoundException("受信生产文件不存在。", full);
        }
        return full;
    }

    private static void AssertNoLinkEscape(string root, string path)
    {
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        var current = new FileInfo(path);
        if (current.Exists && current.LinkTarget is not null)
        {
            throw new InvalidDataException("PRODUCTION_SYMLINK_FORBIDDEN");
        }
        var parent = current.Directory;
        while (parent is not null
               && parent.FullName.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
        {
            if (parent.LinkTarget is not null)
            {
                throw new InvalidDataException("PRODUCTION_SYMLINK_FORBIDDEN");
            }
            if (string.Equals(parent.FullName, fullRoot, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            parent = parent.Parent;
        }
    }

    private static bool IsDesktopResourceTree(string path) =>
        path.Replace('/', '\\').Contains("\\resources\\ComfyUI", StringComparison.OrdinalIgnoreCase);

    private static async Task<string> Sha256FileAsync(
        string path,
        CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 1024 * 1024,
            options: FileOptions.Asynchronous | FileOptions.SequentialScan);
        var digest = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
        return Convert.ToHexString(digest).ToLowerInvariant();
    }

    private static bool IsRetryable(Exception exception, CancellationToken cancellationToken) =>
        exception is HttpRequestException
        || exception is TimeoutException
        || (exception is TaskCanceledException && !cancellationToken.IsCancellationRequested);

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
        if (_ownsComfy)
        {
            await _comfy.DisposeAsync().ConfigureAwait(false);
        }
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