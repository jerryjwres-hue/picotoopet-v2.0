using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.Desktop.Services;

/// <summary>仅首次实机三镜头验收使用；配置不存在时沿用原无人值守调度。</summary>
internal static class P0ThreeShotAcceptanceGate
{
    internal static string DefaultPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "PicotooPetV2", "MediaWorker", "v1", "three-shot-acceptance.json");

    // ── 首次看到验收配置就写入持久 armed 标记；进程重启不解除门禁。 ──
    private enum Mode { Unattended, Hold, Allow, AllowLtxBatch }
    private sealed record Entry(string JobId, string PlanDigest);
    private sealed record Snapshot(Mode Mode, string? JobId = null, string? PlanDigest = null,
        Entry[]? Batch = null)
    {
        // 01. Bind order and exact digests so a gate edit between discovery
        //     and acquisition cannot substitute or reorder a renderer job.
        public string? BatchIdentity => Batch is null ? null : ProductionSubmissionJournal.Hash(
            string.Join("\n", Batch.Select(item => item.JobId + ":" + item.PlanDigest)));
    }
    internal sealed record LtxSelection(ProductionJobRecord? Job, string? BatchIdentity,
        IReadOnlyList<ProductionJobRecord>? SettledJobs = null);

    // Candidate lookup only; execution still rechecks the Plan and retains
    // the exact existing permit. Unattended never selects a B pilot.
    internal static bool HasExplicitAllowFor(string jobId)
    {
        var gate = Read();
        return gate.Mode == Mode.Allow && gate.JobId == jobId;
    }

    // 02. Read the three explicitly named Core jobs in operator order.
    //     Only the first uncompleted shot may run. A failed, uncertain or
    //     already-out-of-order job blocks the remaining batch.
    internal static async Task<LtxSelection?> SelectLtxAsync(ControlCenterSession session,
        IReadOnlyList<ProductionJobRecord> listed, CancellationToken ct)
    {
        var gate = Read();
        if (gate.Mode == Mode.Allow)
        {
            var one = listed.FirstOrDefault(job => LtxProductionExecutor.IsSelected(job)
                && job.ProductionJobId == gate.JobId && job.PlanDigest == gate.PlanDigest);
            return one is null ? null : new(one, null);
        }
        if (gate.Mode != Mode.AllowLtxBatch || gate.Batch is null) return null;

        using var core = session.CreateWorkerChallengePreflightClient();
        var jobs = new List<ProductionJobRecord>();
        var refs = new List<ProductionReferenceAssetV11Record>();
        foreach (var entry in gate.Batch)
        {
            var job = await session.GetProductionJobAsync(entry.JobId, ct).ConfigureAwait(false);
            if (job.ProductionJobId != entry.JobId || job.PlanDigest != entry.PlanDigest
                || (!LtxProductionExecutor.IsSelected(job) && !LtxProductionExecutor.IsCandidateSettled(job)))
                return null;
            var plan = await core.GetLtxPlanAsync(entry.JobId, ct).ConfigureAwait(false);
            var reference = LtxProductionExecutor.ValidatePlan(job, plan, allowSettled: true);
            if (jobs.Count > 0 && (job.CreativePackageId != jobs[0].CreativePackageId
                || job.CreativePackageDigest != jobs[0].CreativePackageDigest || job.ProjectKey != jobs[0].ProjectKey
                || reference.ApprovalId != refs[0].ApprovalId
                || reference.ApprovalRequestDigest != refs[0].ApprovalRequestDigest))
                return null;
            // 03. Require the exact same ordered keys created by reviewed
            //     three-shot freeze. Never accept unrelated single-shot jobs.
            var expectedKey = "reviewed-ltx-pilot-v12-" + reference.ApprovalId + "-"
                + reference.ApprovalRequestDigest + "-shot-" + (jobs.Count + 1);
            if (job.IdempotencyKey != expectedKey
                || refs.Any(x => x.ShotId == reference.ShotId || x.AssetId == reference.AssetId
                    || x.Sha256 == reference.Sha256 || x.ProductionTaskId == reference.ProductionTaskId))
                return null;
            jobs.Add(job);
            refs.Add(reference);
        }
        // 04. All three candidate settlements unlock only CPU rough-cut
        //     assembly, not visual approval or a legacy PASS package.
        if (jobs.All(LtxProductionExecutor.IsCandidateSettled))
            return new(null, gate.BatchIdentity, jobs.AsReadOnly());
        var next = NextLtxBatchJob(jobs);
        return next is null ? null : new(next, gate.BatchIdentity);
    }

    internal static ProductionJobRecord? NextLtxBatchJob(IReadOnlyList<ProductionJobRecord> jobs)
    {
        if (jobs.Count != 3) return null;
        var first = jobs.FirstOrDefault(job => !LtxProductionExecutor.IsCandidateSettled(job));
        if (first is null || !LtxProductionExecutor.IsSelected(first)) return null;
        var index = Array.IndexOf(jobs.ToArray(), first);
        if (jobs.Skip(index).Any(job => !LtxProductionExecutor.IsSelected(job))) return null;
        return first;
    }

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
            if (plan.SchemaVersion == "1.1")
            {
                // The first B pilot is one sealed four-second I2V shot. Reuse the
                // same exact ALLOW/armed-marker/held-file permit and Core facts.
                if (job.ProductionJobId != jobId || plan.ProductionJobId != jobId
                    || job.PlanDigest != gate.PlanDigest || plan.CreativePackageId != job.CreativePackageId
                    || plan.CreativePackageDigest != job.CreativePackageDigest || plan.ProjectKey != job.ProjectKey
                    || plan.ProductionProfile != "production.comfyui.v1" || plan.TargetRuntimeMs != 4000
                    || plan.Tasks is not { Length: 1 }) return false;
                ProductionExecutionService.ValidateV11FrozenReferenceIdentities(jobId, plan);
                var pilot = plan.Tasks[0];
                if (string.IsNullOrWhiteSpace(pilot.ProductionTaskId) || string.IsNullOrWhiteSpace(pilot.ShotId)
                    || pilot.Order != 1 || pilot.RenderIntent != "IMAGE_TO_VIDEO" || pilot.TargetDurationMs != 4000
                    || pilot.FrameCount != 97 || pilot.Fps != 24
                    // Existing signed v1.1 pilot can use either frozen Core output profile;
                    // v1.0 three-shot approval rules and every other permit check stay unchanged.
                    || !((pilot.Width == 832 && pilot.Height == 480)
                        || (pilot.Width == 480 && pilot.Height == 832))) return false;
                return Convert.ToHexStringLower(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))) == gate.PlanDigest;
            }
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

    // 04. Only a deliberate desktop action may arm the existing local gate.
    //     Keep the shared GPU lock and pending journal boundary unchanged.
    internal static void ArmReviewedLtxJobs(IReadOnlyList<ProductionJobRecord> jobs)
    {
        var journal = new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot);
        using var gpu = journal.AcquireGpu();
        if (journal.Pending().Count != 0)
            throw new ProductionWorkerException("MEDIA_PENDING_RECONCILIATION");
        ArmReviewedLtxJobsAtPath(jobs, DefaultPath);
    }

    internal static void ArmReviewedLtxJobsAtPath(IReadOnlyList<ProductionJobRecord> jobs, string path)
    {
        // 05. This method writes only the narrow exact operator permit.
        //     It cannot register references, claim leases or issue media POST.
        if (jobs.Count is not (1 or 3) || jobs.Any(job => !LtxProductionExecutor.IsSelected(job)
            || !ValidJobId(job.ProductionJobId) || !ValidDigest(job.PlanDigest))
            || jobs.Select(job => job.ProductionJobId).Distinct(StringComparer.Ordinal).Count() != jobs.Count
            || jobs.Select(job => job.PlanDigest).Distinct(StringComparer.Ordinal).Count() != jobs.Count
            || jobs.Any(job => job.CreativePackageId != jobs[0].CreativePackageId
                || job.CreativePackageDigest != jobs[0].CreativePackageDigest || job.ProjectKey != jobs[0].ProjectKey))
            throw new ProductionWorkerException("LTX_OPERATOR_BATCH_INVALID");
        var raw = jobs.Count == 1
            ? JsonSerializer.SerializeToUtf8Bytes(new { schema_version = "1.0", mode = "allow",
                production_job_id = jobs[0].ProductionJobId, plan_digest = jobs[0].PlanDigest })
            : JsonSerializer.SerializeToUtf8Bytes(new { schema_version = "1.1", mode = "allow_ltx_batch",
                jobs = jobs.Select(job => new { production_job_id = job.ProductionJobId, plan_digest = job.PlanDigest }) });
        if (raw.Length > 1024) throw new ProductionWorkerException("LTX_OPERATOR_BATCH_INVALID");

        // 06. Existing valid HOLD is the only writable starting mode.
        //     A different ALLOW or corrupt/missing armed file must not be
        //     silently overwritten. FileShare.None protects the pinned POST.
        for (DirectoryInfo? current = new(Path.GetDirectoryName(path)!);
            current is not null; current = current.Parent)
            if (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("P0_ACCEPTANCE_PATH_INVALID");
        if (!File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new ProductionWorkerException("LTX_OPERATOR_HOLD_REQUIRED");
        using var stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None,
            bufferSize: 4096, options: FileOptions.WriteThrough);
        if (stream.Length is <= 0 or > 1024)
            throw new ProductionWorkerException("LTX_OPERATOR_HOLD_REQUIRED");
        var prior = new byte[(int)stream.Length];
        stream.ReadExactly(prior);
        if (prior.AsSpan().SequenceEqual(raw)) return;
        using var currentDocument = JsonDocument.Parse(prior);
        var currentRoot = currentDocument.RootElement;
        if (currentRoot.ValueKind != JsonValueKind.Object || currentRoot.EnumerateObject().Count() != 2
            || !currentRoot.TryGetProperty("schema_version", out var version) || version.ValueKind != JsonValueKind.String
            || version.GetString() != "1.0" || !currentRoot.TryGetProperty("mode", out var mode)
            || mode.ValueKind != JsonValueKind.String || mode.GetString() != "hold")
            throw new ProductionWorkerException("LTX_OPERATOR_HOLD_REQUIRED");
        var markerPath = path + ".armed";
        if (!MarkerExists(markerPath))
        {
            using var marker = new FileStream(markerPath, FileMode.CreateNew, FileAccess.Write,
                FileShare.Read, 8, FileOptions.WriteThrough);
            marker.WriteByte(1);
            marker.Flush(flushToDisk: true);
        }
        // 07. A crash during exclusive write leaves invalid JSON (HOLD).
        //     The durable armed marker prevents deletion from enabling work.
        stream.Position = 0;
        stream.SetLength(0);
        stream.Write(raw);
        stream.Flush(flushToDisk: true);
    }

    // 08. LTX alone may consume a batch permit. Legacy Wan permits below
    //     cannot use batch entries, and missing config never authorizes LTX.
    internal static IDisposable AcquireLtxSubmissionPermit(string jobId, string planDigest, string? batchIdentity) =>
        AcquireLtxSubmissionPermitAtPath(jobId, planDigest, batchIdentity, DefaultPath);

    internal static IDisposable AcquireLtxSubmissionPermitAtPath(
        string jobId, string planDigest, string? batchIdentity, string path)
    {
        FileStream? stream = null;
        try
        {
            stream = OpenGate(path) ?? throw new IOException("LTX_EXPLICIT_PERMIT_REQUIRED");
            var gate = Parse(stream);
            var allowed = batchIdentity is null
                ? gate.Mode == Mode.Allow && gate.JobId == jobId && gate.PlanDigest == planDigest
                : gate.Mode == Mode.AllowLtxBatch && gate.BatchIdentity == batchIdentity
                    && gate.Batch!.Any(item => item.JobId == jobId && item.PlanDigest == planDigest);
            if (!allowed) throw new IOException("LTX_EXPLICIT_PERMIT_REQUIRED");
            return stream;
        }
        catch (Exception error) when (error is not OutOfMemoryException)
        {
            stream?.Dispose();
            throw new ProductionWorkerException("P0_THREE_SHOT_ACCEPTANCE_HELD");
        }
    }

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
        if (stream.Length is <= 0 or > 1024)
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
            || version.ValueKind != JsonValueKind.String
            || !root.TryGetProperty("mode", out var mode)
            || mode.ValueKind != JsonValueKind.String)
            return new(Mode.Hold);
        var count = root.EnumerateObject().Count();
        // 05. New explicit batch mode is distinct from the old exact single
        //     job gate. Reject extra/duplicate keys, nil IDs and duplicates.
        if (version.GetString() == "1.1")
        {
            if (mode.GetString() != "allow_ltx_batch" || count != 3
                || !root.TryGetProperty("jobs", out var jobs) || jobs.ValueKind != JsonValueKind.Array
                || jobs.GetArrayLength() != 3) return new(Mode.Hold);
            var entries = new List<Entry>();
            foreach (var item in jobs.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object || item.EnumerateObject().Count() != 2
                    || !item.TryGetProperty("production_job_id", out var id) || id.ValueKind != JsonValueKind.String
                    || !item.TryGetProperty("plan_digest", out var hash) || hash.ValueKind != JsonValueKind.String
                    || !ValidJobId(id.GetString()) || !ValidDigest(hash.GetString())
                    || entries.Any(x => x.JobId == id.GetString() || x.PlanDigest == hash.GetString()))
                    return new(Mode.Hold);
                entries.Add(new(id.GetString()!, hash.GetString()!));
            }
            return new(Mode.AllowLtxBatch, Batch: entries.ToArray());
        }
        if (version.GetString() != "1.0" || stream.Length > 512) return new(Mode.Hold);
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

    private static bool ValidJobId(string? value) =>
        Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty && id.ToString("D") == value;

    private static bool ValidDigest(string? value) =>
        value is { Length: 64 } && value.All(c => c is (>= '0' and <= '9') or (>= 'a' and <= 'f'));
}
