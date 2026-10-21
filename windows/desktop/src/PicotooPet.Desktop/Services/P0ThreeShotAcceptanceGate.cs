using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services;

/// <summary>仅首次实机三镜头验收使用；配置不存在时沿用原无人值守调度。</summary>
internal static class P0ThreeShotAcceptanceGate
{
    internal static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPetV2", "MediaWorker", "v1", "three-shot-acceptance.json");

    // ── Worker 曾读取过门禁后，删除文件不能在同一进程内重新打开全量调度。 ──
    private static int _observedGate;
    private enum Mode { Unattended, Hold, Allow }
    private sealed record Snapshot(Mode Mode, string? JobId = null, string? PlanDigest = null);

    /// <summary>只读 Core 的不可变 Plan 和真实 digest；失败时不领取 lease 或启动 GPU。</summary>
    internal static async Task<bool> AllowsJobAsync(
        ControlCenterSession session, string jobId, CancellationToken cancellationToken)
    {
        var gate = Read();
        if (gate.Mode == Mode.Unattended) return true;
        if (gate.Mode != Mode.Allow || gate.JobId != jobId) return false;

        try
        {
            var jobTask = session.GetProductionJobAsync(jobId, cancellationToken);
            var planTask = session.GetProductionPlanAsync(jobId, cancellationToken);
            await Task.WhenAll(jobTask, planTask).ConfigureAwait(false);
            var job = await jobTask.ConfigureAwait(false);
            var plan = await planTask.ConfigureAwait(false);
            if (job.ProductionJobId != jobId
                || plan.ProductionJobId != jobId
                || job.PlanDigest != gate.PlanDigest
                || plan.CreativePackageId != job.CreativePackageId
                || plan.CreativePackageDigest != job.CreativePackageDigest
                || plan.ProjectKey != job.ProjectKey
                || plan.SchemaVersion != "1.0"
                || plan.ProductionProfile != "production.comfyui.v1"
                || plan.Tasks is not { Length: 3 }
                || plan.Tasks.Select(task => task.Order).Where((order, index) => order != index + 1).Any()
                || plan.Tasks.Select(task => task.ProductionTaskId).Distinct(StringComparer.Ordinal).Count() != 3
                || plan.Tasks.Select(task => task.ShotId).Distinct(StringComparer.Ordinal).Count() != 3
                || plan.Tasks.Any(task =>
                    task.RenderIntent != "GENERATIVE_VIDEO"
                    || task.ExecutionDisposition != "Executable"
                    || task.WorkflowId != ComfyWorkflowTemplateValidator.T2VWorkflowId
                    || task.TrustedInputAssetRef is not null
                    || task.ReferenceAsset is not null))
            {
                return false;
            }
            // ── 与现有 executor 的 Journal plan digest 使用同一个规范化 JSON 实现。 ──
            var actualDigest = Convert.ToHexString(SHA256.HashData(
                CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))).ToLowerInvariant();
            return actualDigest == gate.PlanDigest;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception)
        {
            // ── 配对断线、Core 未就绪及 Plan 冲突均暂停，不降级到普通调度。 ──
            return false;
        }
    }

    /// <summary>
    /// 在每次新增 Comfy POST 的预留阶段持有只读文件句柄；
    /// Windows 写者无法在 POST 调用期间替换授权文件，已提交的 prompt 不会被撤回。
    /// </summary>
    internal static IDisposable? AcquireSubmissionPermit(string jobId, string planDigest)
    {
        FileStream? stream = null;
        try
        {
            stream = OpenGate();
            if (stream is null) return null; // ── 默认无人值守完全不变。 ──
            var gate = Parse(stream);
            if (gate.Mode != Mode.Allow || gate.JobId != jobId || gate.PlanDigest != planDigest)
                throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD");
            return stream;
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            stream?.Dispose();
            throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD");
        }
    }

    /// <summary>无文件表示原模式；有文件但任何错误均只能解释为 HOLD。</summary>
    private static Snapshot Read()
    {
        try
        {
            using var stream = OpenGate();
            return stream is null ? new(Mode.Unattended) : Parse(stream);
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            return new(Mode.Hold);
        }
    }

    private static FileStream? OpenGate()
    {
        var path = DefaultPath;
        // ── 固定本地目录及每层重解析点均不可信，不允许路径替换绕过门禁。 ──
        for (DirectoryInfo? current = new(Path.GetDirectoryName(path)!);
            current is not null; current = current.Parent)
        {
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("P0_ACCEPTANCE_PATH_INVALID");
        }
        if (!File.Exists(path))
        {
            if (System.Threading.Volatile.Read(ref _observedGate) != 0)
                throw new IOException("P0_ACCEPTANCE_FILE_MISSING");
            return null;
        }
        System.Threading.Interlocked.Exchange(ref _observedGate, 1);
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("P0_ACCEPTANCE_PATH_INVALID");
        var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is <= 0 or > 512)
        {
            stream.Dispose();
            throw new IOException("P0_ACCEPTANCE_FILE_INVALID");
        }
        return stream;
    }

    private static Snapshot Parse(Stream stream)
    {
        using var document = JsonDocument.Parse(stream);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("schema_version", out var version)
            || version.ValueKind != JsonValueKind.String || version.GetString() != "1.0"
            || !root.TryGetProperty("mode", out var mode)
            || mode.ValueKind != JsonValueKind.String)
            return new(Mode.Hold);
        var count = root.EnumerateObject().Count();
        if (mode.GetString() == "hold" && count == 2)
            return new(Mode.Hold);
        if (mode.GetString() != "allow" || count != 4
            || !root.TryGetProperty("production_job_id", out var job)
            || !root.TryGetProperty("plan_digest", out var digest)
            || job.ValueKind != JsonValueKind.String
            || digest.ValueKind != JsonValueKind.String)
            return new(Mode.Hold);
        var jobId = job.GetString();
        var sha = digest.GetString();
        if (!Guid.TryParseExact(jobId, "D", out _)
            || jobId != jobId!.ToLowerInvariant()
            || sha is null || sha.Length != 64
            || sha.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            return new(Mode.Hold);
        return new(Mode.Allow, jobId, sha);
    }
}
