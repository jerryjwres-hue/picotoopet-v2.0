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

    // ── 首次看到验收配置就写入持久 armed 标记；进程重启不解除门禁。 ──
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
                    // ── 身份必须非空白；Distinct 无法拒绝单个空 ShotId/TaskId。 ──
                    string.IsNullOrWhiteSpace(task.ProductionTaskId)
                    || string.IsNullOrWhiteSpace(task.ShotId)
                    || task.RenderIntent != "GENERATIVE_VIDEO"
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
    internal static IDisposable? AcquireSubmissionPermit(string jobId, string planDigest) =>
        AcquireSubmissionPermitAtPath(jobId, planDigest, DefaultPath);

    // ── 参数化只读入口供现有 Windows smoke 使用；正式入口仍固定 LocalAppData。 ──
    internal static IDisposable? AcquireSubmissionPermitAtPath(string jobId, string planDigest, string path)
    {
        FileStream? stream = null;
        try
        {
            stream = OpenGate(path);
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
            using var stream = OpenGate(DefaultPath);
            return stream is null ? new(Mode.Unattended) : Parse(stream);
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            return new(Mode.Hold);
        }
    }

    private static FileStream? OpenGate(string path)
    {
        // ── 既有目录的重解析点不能用于替换验收文件或 armed 标记。 ──
        for (DirectoryInfo? current = new(Path.GetDirectoryName(path)!);
            current is not null; current = current.Parent)
        {
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("P0_ACCEPTANCE_PATH_INVALID");
        }
        var markerPath = path + ".armed";
        FileAttributes gateAttributes;
        try
        {
            gateAttributes = File.GetAttributes(path);
        }
        catch (FileNotFoundException)
        {
            // ── 尚未启用过时维持旧无人值守；已 armed 时删除配置只能 HOLD。 ──
            if (MarkerExists(markerPath))
                throw new IOException("P0_ACCEPTANCE_FILE_MISSING");
            return null;
        }
        catch (DirectoryNotFoundException)
        {
            if (MarkerExists(markerPath))
                throw new IOException("P0_ACCEPTANCE_FILE_MISSING");
            return null;
        }
        if ((gateAttributes & FileAttributes.ReparsePoint) != 0)
            throw new IOException("P0_ACCEPTANCE_PATH_INVALID");

        // ── 先持久化 armed，再读取 HOLD/ALLOW；写入失败不能降级无人值守。 ──
        if (MarkerExists(markerPath) == false)
        {
            using var marker = new FileStream(markerPath, FileMode.OpenOrCreate, FileAccess.Write,
                FileShare.Read, bufferSize: 8, options: FileOptions.WriteThrough);
            if (marker.Length == 0)
            {
                marker.WriteByte(1);
                marker.Flush(flushToDisk: true);
            }
        }
        var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length is <= 0 or > 512)
        {
            stream.Dispose();
            throw new IOException("P0_ACCEPTANCE_FILE_INVALID");
        }
        return stream;
    }

    private static bool MarkerExists(string markerPath)
    {
        try
        {
            var attributes = File.GetAttributes(markerPath);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("P0_ACCEPTANCE_MARKER_INVALID");
            return true;
        }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
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
        if (!Guid.TryParseExact(jobId, "D", out var parsedJobId)
            || !string.Equals(jobId, parsedJobId.ToString("D"), StringComparison.Ordinal)
            || sha is null || sha.Length != 64
            || sha.Any(c => c is not (>= '0' and <= '9') and not (>= 'a' and <= 'f')))
            return new(Mode.Hold);
        return new(Mode.Allow, jobId, sha);
    }
}
