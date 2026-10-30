using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services.QualityObservation;

public sealed class VisualReviewObservation : IVisualObservation
{
    internal static readonly JsonSerializerOptions Json = new()
    { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow, MaxDepth = 32 };
    private readonly IVisualObservationFacts _facts;
    private readonly IVisualObservationRuntime _runtime;
    public VisualReviewObservation(IVisualObservationFacts facts, IVisualObservationRuntime runtime)
    { _facts = facts; _runtime = runtime; _facts.Invalidated += Changed; }
    public static IVisualObservation Create(ControlCenterSession session) =>
        new VisualReviewObservation(new SessionVisualObservationFacts(session), new DeployedVisualObservationRuntime());
    public event EventHandler? Invalidated;
    private void Changed(object? sender, EventArgs e) => Invalidated?.Invoke(this, e);
    public void Dispose() { _facts.Invalidated -= Changed; _facts.Dispose(); }
    public static bool IsSha(string? value) => value is not null && Regex.IsMatch(value, "^[a-f0-9]{64}$") && value.Any(c => c != '0');
    private static void Require(bool condition, string code) { if (!condition) throw new VisualObservationException(code); }
    private static string Hash(System.Text.Json.Nodes.JsonNode node) => Convert.ToHexStringLower(SHA256.HashData(CanonicalJson.Serialize(node)));
    private static string Fingerprint(VisualObservationFacts f) => Hash(JsonSerializer.SerializeToNode(f)!);

    public async Task<VisualObservationResult> ObserveAsync(ProductionJobRecord selected, bool optionalVlm,
        Func<VisualReadRequest, CancellationToken, Task<VisualReadConsent>> consent, CancellationToken ct)
    {
        using var budget = CancellationTokenSource.CreateLinkedTokenSource(ct); budget.CancelAfter(TimeSpan.FromMinutes(5));
        var token = budget.Token;
        var pins = new List<VisualEvidenceFileLease>();
        try
        {
            var facts = await _facts.ReadAsync(selected.ProductionJobId, token).WaitAsync(token).ConfigureAwait(false);
            facts = JsonSerializer.Deserialize<VisualObservationFacts>(JsonSerializer.Serialize(facts))!;
            var input = Validate(selected, facts);
            var fingerprint = Fingerprint(facts);
            var root = DeployedVisualObservationRuntime.LocalPath(_runtime.ConfiguredOutputRoot());
            var paths = input.Shots.Select(s => SourcePath(root, s.RelativePath)).ToArray();
            using var deployment = _runtime.OpenDeployment();
            if (optionalVlm) Require(deployment.VlmEndpoint is not null && deployment.VlmModel is not null, "VLM_NOT_CONFIGURED");
            var request = new VisualReadRequest(input.JobId, input.Shots.Select((s, i) =>
                new VisualReadSource(paths[i], s.ShotId, s.TaskId, s.Sha256, s.Bytes)).ToArray(),
                optionalVlm ? deployment.VlmEndpoint : null, optionalVlm ? deployment.VlmModel : null);
            var answer = await consent(request, token).WaitAsync(token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            if (!answer.ReadSources) return Unverified("未同意读取三段来源；未运行审核工具。");
            var transfer = optionalVlm && answer.TransferFrames;
            await RecheckFactsAsync(selected, fingerprint, token).ConfigureAwait(false);
            Require(_runtime.ConfiguredOutputRoot() == root, "OUTPUT_ROOT_CHANGED");
            for (var i = 0; i < paths.Length; i++)
            {
                pins.Add(new VisualEvidenceFileLease(paths[i]));
                await CheckSourceAsync(paths[i], input.Shots[i], token).ConfigureAwait(false);
                pins[^1].Recheck();
            }
            var run = Path.GetFullPath(_runtime.CreateEvidenceRun());
            Require(!run.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                && !string.Equals(run, root, StringComparison.OrdinalIgnoreCase), "EVIDENCE_INSIDE_SOURCE");
            ProductionLocalEnvironment.AssertNoLinkEscape(Path.GetPathRoot(run)!, run);
            using var outputNamespace = new ProductionReference.WorkerKeyNamespace(run);
            var manifest = Path.Combine(run, "input.json");
            await WriteNewAsync(manifest, JsonSerializer.SerializeToUtf8Bytes(input, Json), token).ConfigureAwait(false);
            // Provenance only, never a QA receipt or terminal state. ZIP package
            // digest is opaque Core authority; it is not a JSON-manifest hash.
            await WriteNewAsync(Path.Combine(run, "source-provenance.json"), JsonSerializer.SerializeToUtf8Bytes(new
            {
                schema_version = "visual_observation.provenance.v1", authority = "NONE",
                job_id = input.JobId, plan_digest = facts.Job.PlanDigest, package_id = facts.Package.ProductionPackageId,
                package_digest = facts.Package.PackageDigest, facts_fingerprint = fingerprint,
                observer_source_sha256 = deployment.SourceSha, frame_transfer_consented = transfer,
                human_accept = "NOT_GRANTED",
            }), token).ConfigureAwait(false);
            var output = Path.Combine(run, "evidence");
            token.ThrowIfCancellationRequested();
            // The runtime owns bounded child termination; keep all source/tool
            // pins until its cleanup completes, including cancellation.
            var exit = await _runtime.RunAsync(deployment, manifest, root, output, transfer, token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            Require(exit == 0, "OBSERVER_FAILED");
            for (var i = 0; i < paths.Length; i++)
            { pins[i].Recheck(); await CheckSourceAsync(paths[i], input.Shots[i], token).ConfigureAwait(false); pins[i].Recheck(); }
            await RecheckFactsAsync(selected, fingerprint, token).ConfigureAwait(false);
            Require(_runtime.ConfiguredOutputRoot() == root, "OUTPUT_ROOT_CHANGED");
            return await ReadReportAsync(input, output, transfer, token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) { return Unverified("观察已取消或超时；旧结果不可作为审片结论。"); }
        catch (VisualObservationException e)
        {
            return Unverified(e.Message switch
            {
                "OBSERVER_NOT_DEPLOYED" => "缺少已部署且由应用内受信清单绑定的审核工具；未运行工具。",
                "OUTPUT_ROOT_UNVERIFIED" => "缺少可验证的本地 ComfyUI 配置输出目录；不会猜测或搜索路径。",
                "VLM_NOT_CONFIGURED" => "没有已批准的局域网模型配置；未发送帧或下载模型。",
                _ => "来源、身份、部署或报告证据未通过只读校验；未改变生产状态。",
            });
        }
        catch (Exception) { return Unverified("只读视觉观察未完成；来源、工具或权限不足，未改变生产状态。"); }
        finally { foreach (var pin in pins) pin.Dispose(); }
    }
    public static VisualObservationResult Unverified(string detail) => new(VisualObservationVerdict.Unverified, detail);
    private async Task RecheckFactsAsync(ProductionJobRecord selected, string expected, CancellationToken ct)
    {
        var current = await _facts.ReadAsync(selected.ProductionJobId, ct).WaitAsync(ct).ConfigureAwait(false);
        _ = Validate(selected, current); Require(Fingerprint(current) == expected, "SOURCE_FACTS_CHANGED");
    }
    public static VisualObservationInput Validate(ProductionJobRecord selected, VisualObservationFacts facts)
    {
        var j = facts.Job; var p = facts.Plan; var package = facts.Package; var m = package.Manifest;
        Require(Guid.TryParse(j.ProductionJobId, out _) && j.ProductionJobId == selected.ProductionJobId
            && selected.PlanDigest == j.PlanDigest && selected.CreativePackageId == j.CreativePackageId
            && selected.CreativePackageDigest == j.CreativePackageDigest && selected.ProjectKey == j.ProjectKey
            && selected.Status == "production_ready" && j.Status == "production_ready"
            && j.FinishedAt is not null && j.LeaseExecutorId is null && j.LeaseExpiresAt is null
            && IsSha(j.PlanDigest) && IsSha(j.CreativePackageDigest) && IsSha(package.PackageDigest)
            && Guid.TryParse(package.ProductionPackageId, out _) && package.ProductionJobId == j.ProductionJobId
            && package.CreativePackageId == j.CreativePackageId && package.PlanDigest == j.PlanDigest && package.QualityOutcome == "PASS"
            && p.SchemaVersion is "1.0" or "1.1" && p.ProductionJobId == j.ProductionJobId
            && p.CreativePackageId == j.CreativePackageId && p.CreativePackageDigest == j.CreativePackageDigest
            && p.ProjectKey == j.ProjectKey && p.ProductionProfile == j.ProductionProfile && j.ProductionProfile == "production.comfyui.v1"
            && p.Tasks is { Length: 3 } && Hash(JsonSerializer.SerializeToNode(p)!) == j.PlanDigest, "FACTS_MISMATCH");
        Require(m.ValueKind == JsonValueKind.Object && Text(m, "schema_version") == "1.0"
            && Text(m, "production_job_id") == j.ProductionJobId && Text(m, "production_package_id") == package.ProductionPackageId
            && Text(m, "creative_package_id") == j.CreativePackageId && Text(m, "creative_package_digest") == j.CreativePackageDigest
            && Text(m, "plan_digest") == j.PlanDigest && Text(m, "production_profile") == j.ProductionProfile
            && m.GetProperty("outputs").GetArrayLength() == 3, "PACKAGE_MISMATCH");
        var tasks = p.Tasks.OrderBy(t => t.Order).ToArray();
        var outputs = m.GetProperty("outputs").EnumerateArray().ToArray();
        var ids = new HashSet<string>(StringComparer.Ordinal); var shots = new HashSet<string>(StringComparer.Ordinal);
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase); var result = new List<VisualObservationShot>();
        for (var i = 0; i < 3; i++)
        {
            var task = tasks[i];
            Require(task.Order == i + 1 && Id(task.ProductionTaskId) && Id(task.ShotId)
                && ids.Add(task.ProductionTaskId) && shots.Add(task.ShotId)
                && task.Width is >= 16 and <= 8192 && task.Height is >= 16 and <= 8192
                && task.FrameCount is >= 1 and <= 10000 && task.Fps is >= 1 and <= 240
                && task.TargetDurationMs is >= 250 and <= 60000 && task.PositivePrompt is { Length: <= 1000 }, "TASK_MISMATCH");
            var matches = outputs.Where(o => Text(o, "production_task_id") == task.ProductionTaskId).ToArray();
            Require(matches.Length == 1, "OUTPUT_MISMATCH"); var o = matches[0];
            var relative = Text(o, "output_relpath"); var sha = Text(o, "output_sha256"); var bytes = o.GetProperty("output_bytes").GetInt64();
            Require(Text(o, "shot_id") == task.ShotId && Text(o, "mime_type") == "video/webm"
                && relative.EndsWith(".webm", StringComparison.OrdinalIgnoreCase) && paths.Add(relative) && IsSha(sha)
                && bytes is >= 128 and <= 1073741824 && o.GetProperty("frame_count").GetInt32() == task.FrameCount
                && o.GetProperty("fps").GetInt32() == task.Fps && o.GetProperty("width").GetInt32() == task.Width
                && o.GetProperty("height").GetInt32() == task.Height, "OUTPUT_MISMATCH");
            result.Add(new(task.Order, task.ShotId, task.ProductionTaskId, relative, sha, bytes,
                task.FrameCount, checked((int)task.TargetDurationMs), task.PositivePrompt));
        }
        return new("visual_review.input.v1", j.ProductionJobId, result.ToArray());
    }
    private static bool Id(string value) => Regex.IsMatch(value, "^[a-zA-Z0-9_-]{1,80}$");
    private static string Text(JsonElement e, string name) => e.GetProperty(name).GetString() ?? "";
    private static string SourcePath(string root, string relative)
    {
        Require(!string.IsNullOrWhiteSpace(relative) && !Path.IsPathRooted(relative) && relative.Length <= 500
            && !relative.Contains(':', StringComparison.Ordinal)
            && relative.Split(['/', '\\']).All(p => p is not ("" or "." or "..") && p.IndexOfAny(Path.GetInvalidFileNameChars()) < 0), "SOURCE_PATH_INVALID");
        var path = ProductionLocalEnvironment.ResolveUnderRoot(root, relative, false);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path); return path;
    }
    private static async Task CheckSourceAsync(string path, VisualObservationShot shot, CancellationToken ct)
    {
        Require(ProductionLocalEnvironment.IsOrdinaryFile(path) && new FileInfo(path).Length == shot.Bytes, "SOURCE_CHANGED");
        using (var stream = File.OpenRead(path))
        {
            var header = new byte[4]; await stream.ReadExactlyAsync(header, ct).ConfigureAwait(false);
            Require(header.AsSpan().SequenceEqual(new byte[] { 0x1a, 0x45, 0xdf, 0xa3 }), "SOURCE_NOT_WEBM");
        }
        Require(await ProductionLocalEnvironment.Sha256FileAsync(path, ct).ConfigureAwait(false) == shot.Sha256, "SOURCE_CHANGED");
    }
    private static async Task WriteNewAsync(string path, byte[] bytes, CancellationToken ct)
    {
        await using var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        await file.WriteAsync(bytes, ct).ConfigureAwait(false);
    }
    private static async Task<byte[]> ReadEvidenceAsync(string output, string relative, string sha, long length, int maximum, CancellationToken ct)
    {
        Require(length > 0 && length <= maximum && IsSha(sha), "EVIDENCE_INVALID");
        var path = SourcePath(output, relative);
        using var pin = new VisualEvidenceFileLease(path);
        Require(new FileInfo(path).Length == length, "EVIDENCE_INVALID");
        var bytes = await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false);
        pin.Recheck(); Require(Convert.ToHexStringLower(SHA256.HashData(bytes)) == sha, "EVIDENCE_CHANGED");
        return bytes;
    }
    private static async Task<VisualObservationResult> ReadReportAsync(VisualObservationInput input, string output, bool transferred, CancellationToken ct)
    {
        var path = Path.Combine(output, "report.json"); using var pin = new VisualEvidenceFileLease(path);
        Require(new FileInfo(path).Length is > 0 and <= 1048576, "REPORT_INVALID");
        using var doc = JsonDocument.Parse(await File.ReadAllBytesAsync(path, ct).ConfigureAwait(false), new JsonDocumentOptions { MaxDepth = 32 });
        pin.Recheck(); var r = doc.RootElement; var status = Text(r, "status"); var model = Text(r, "model_state");
        Require(Text(r, "schema_version") == "visual_review.v1" && Text(r, "job_id") == input.JobId
            && status is "ADVISORY_REVIEW" or "REJECT_SUSPECT"
            && (transferred ? model == "INFERENCE_SUCCEEDED_ADVISORY_ONLY" : model == "NOT_REQUESTED")
            && Text(r, "contact_sheet") == "contact_sheet_3x3.png" && r.GetProperty("shots").GetArrayLength() == 3, "REPORT_INVALID");
        var frames = new HashSet<string>(StringComparer.Ordinal);
        var evidence = r.GetProperty("shots").EnumerateArray().ToArray();
        for (var i = 0; i < 3; i++)
        {
            var shot = input.Shots[i]; var e = evidence[i]; var duration = e.GetProperty("duration_ms").GetInt64();
            Require(e.GetProperty("order").GetInt32() == shot.Order && Text(e, "shot_id") == shot.ShotId && Text(e, "task_id") == shot.TaskId
                && Text(e, "source_file") == shot.RelativePath && Text(e, "source_sha256") == shot.Sha256
                && e.GetProperty("source_bytes").GetInt64() == shot.Bytes && e.GetProperty("frames").GetInt32() == shot.ExpectedFrames
                && duration is > 0 and <= 60000 && Math.Abs(duration - shot.ExpectedDurationMs) <= 250 && e.GetProperty("samples").GetArrayLength() == 3, "REPORT_IDENTITY_MISMATCH");
            var k = 0;
            foreach (var f in e.GetProperty("samples").EnumerateArray())
            {
                var index = i * 3 + k++; var name = $"frame_{index:00}.png";
                Require(f.GetProperty("grid_index").GetInt32() == index && Text(f, "filename") == name
                    && f.GetProperty("shot_order").GetInt32() == shot.Order && Text(f, "shot_id") == shot.ShotId && Text(f, "task_id") == shot.TaskId
                    && f.GetProperty("timecode_ms").GetInt64() == Math.Min(duration - 50, Math.Max(1, duration * k / 4)), "FRAME_IDENTITY_MISMATCH");
                _ = await ReadEvidenceAsync(output, "frames/" + name, Text(f, "sha256"), f.GetProperty("bytes").GetInt64(), 2000000, ct).ConfigureAwait(false);
                frames.Add(name);
            }
        }
        var concerns = r.GetProperty("concerns"); Require(concerns.GetArrayLength() <= 18 && (transferred || concerns.GetArrayLength() == 0), "REPORT_INVALID");
        var uncertain = Text(r, "reviewer_disagreement") != "NOT_FLAGGED";
        var high = false;
        var notes = new List<string>();
        foreach (var c in concerns.EnumerateArray())
        {
            var order = c.GetProperty("shot_order").GetInt32(); var confidence = c.GetProperty("confidence").GetDouble();
            var rationale = Text(c, "rationale"); var category = Text(c, "category"); var severity = Text(c, "severity");
            Require(order is >= 1 and <= 3 && frames.Contains(Text(c, "evidence_filename"))
                && Text(c, "evidence_filename") == $"frame_{(order - 1) * 3 + 1:00}.png"
                && double.IsFinite(confidence) && confidence is >= 0 and <= 1 && rationale.Length is > 0 and <= 400
                && severity is "low" or "medium" or "high"
                && category is "identity_drift" or "scarf_inconsistency" or "floating_object" or "object_support"
                    or "implausible_physics" or "product_geometry" or "story_causality" or "motion" or "other", "CONCERN_UNGROUNDED");
            uncertain |= confidence < 0.5; high |= severity == "high";
            uncertain |= rationale.Contains("ACCEPT", StringComparison.OrdinalIgnoreCase)
                || rationale.Contains("instructions", StringComparison.OrdinalIgnoreCase) || rationale.Contains("指令", StringComparison.Ordinal);
            notes.Add($"镜头 {order} · {category} · {severity} · 模型文本（未验证）：{rationale}");
        }
        Require(status != "REJECT_SUSPECT" || high, "REPORT_INVALID");
        var sheetPath = Path.Combine(output, "contact_sheet_3x3.png");
        var sheet = await ReadEvidenceAsync(output, "contact_sheet_3x3.png", Text(r, "contact_sheet_sha256"), new FileInfo(sheetPath).Length, 10000000, ct).ConfigureAwait(false);
        Require(sheet.Length >= 24 && sheet.AsSpan(0, 8).SequenceEqual(new byte[] { 137,80,78,71,13,10,26,10 })
            && System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(sheet.AsSpan(16,4)) == 976
            && System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(sheet.AsSpan(20,4)) == 556, "GRID_INVALID");
        var verdict = status == "REJECT_SUSPECT" && !uncertain ? VisualObservationVerdict.RejectSuspect : VisualObservationVerdict.Review;
        var detail = transferred ? "工具报告模型推理完成；持续加载状态与感知准确率仍未验证。" : "CPU 九宫格及时间戳证据已生成；未调用模型，等待人工审片。";
        return new(verdict, detail + " 不代表人工 ACCEPT / C011。请复核人物/服装、悬空支撑、商品形状、跨镜头场景和故事因果。\n"
            + string.Join("\n", notes) + "\n证据：" + output, output, sheet);
    }
}
