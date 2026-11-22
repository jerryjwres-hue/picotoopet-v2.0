using System.Collections.ObjectModel;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;
using BitmapDecoder = Windows.Graphics.Imaging.BitmapDecoder;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;
using PicotooPet.ReferencePreview.Codecs;

namespace PicotooPet.Desktop.ViewModels;

public sealed record ReferencePreviewItem(string ShotId, string Sha256, long Bytes,
    string InputRelativePath, string SourceReference, string SourceDigest, BitmapSource Preview);

public sealed record ReferenceKeyframeInstruction(string ShotId, string StillPrompt, string ReviewChecklist);

// 只读候选是历史输出观测，不是 Producer 授权、身份资产或使用许可。
public sealed record ReferenceObservedCandidate(string ShotId, string OutputRelativePath,
    string Sha256, long Bytes, int Width, int Height, string PromptId);

/// <summary>Local preview and explicit request for existing Core approvals; never grants execution permission.</summary>
public sealed class ReferenceBatchPreviewViewModel : ObservableObject
{
    // 固定 P0 顺序：复用同一只读数组，避免重复分配。
    private static readonly int[] P0ShotOrders = [1, 2, 3];
    private readonly IReferenceBatchGateway _gateway;
    private readonly ReferencePreviewSnapshotStager _stager;
    private readonly HashSet<string> _eligibleShots;
    private readonly bool _requiresFullV2Batch;
    private readonly bool _p0PlanCandidate;
    private readonly string _creativeJobId;
    private readonly string _keyframeKitDigest;
    private readonly Dictionary<string, (ReferencePreviewSnapshot Snapshot, ReferencePreviewItem Item)> _snapshots = new(StringComparer.Ordinal);
    private ReferenceBatchRequest? _frozenRequest;
    private ReferenceBatchReceipt? _initialReceipt;
    private ReferenceBatchReceipt? _receipt;
    private ProductionJobRecord? _createdProductionJob;
    private bool _approvalFresh;
    private bool _consent;
    private int _operation;
    private string _statusText = "请选择镜头与参考图，查看预览后确认使用权。";

    public ReferenceBatchPreviewViewModel(IReferenceBatchGateway gateway, ReferencePreviewSnapshotStager stager,
        GoalVideoContinuationRecord continuation, CreativePackageRecord package)
    {
        ArgumentNullException.ThrowIfNull(gateway);
        ArgumentNullException.ThrowIfNull(stager);
        ArgumentNullException.ThrowIfNull(continuation);
        ArgumentNullException.ThrowIfNull(package);
        if (continuation.CreativeStatus != "creative_ready" || package.QualityOutcome != "PASS"
            || !IsIdentifier(continuation.GoalId) || !IsIdentifier(package.CreativePackageId)
            || !IsDigest(package.PackageDigest) || !IsDigest(package.SourceSetDigest)
            || string.IsNullOrWhiteSpace(package.CreativeJobId)
            || continuation.CreativePackageId != package.CreativePackageId
            || continuation.CreativePackageDigest != package.PackageDigest
            || continuation.CreativeJobId != package.CreativeJobId)
            throw new InvalidDataException("REFERENCE_CREATIVE_CONTEXT_INVALID");
        var manifest = package.Manifest;
        if (Text(manifest, "creative_package_id") != package.CreativePackageId
            || Text(manifest, "creative_job_id") != package.CreativeJobId
            || Text(manifest, "quality_outcome") != "PASS"
            || Text(manifest, "source_set_digest") != package.SourceSetDigest
            || !manifest.TryGetProperty("stage_results", out var stages) || stages.ValueKind != JsonValueKind.Object
            || !stages.TryGetProperty("shot_plan.v1", out var plan) || plan.ValueKind != JsonValueKind.Object
            || !plan.TryGetProperty("shots", out var shots) || shots.ValueKind != JsonValueKind.Array)
            throw new InvalidDataException("REFERENCE_CREATIVE_MANIFEST_INVALID");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var eligible = new List<string>();
        foreach (var shot in shots.EnumerateArray())
        {
            var id = Text(shot, "shot_id");
            if (id.Length is < 1 or > 80 || id.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '_' and not '.' and not '-')
                || !seen.Add(id)) throw new InvalidDataException("REFERENCE_PLAN_SHOT_INVALID");
            if (Text(shot, "render_intent") == "IMAGE_TO_VIDEO") eligible.Add(id);
        }
        // ── UI candidate only: real Bible/kit/rights and full coverage are verified by Mac Core.
        // ── Never rewrite a frozen Creative Package or silently include mixed legacy shots.
        var v2Candidate = eligible.Count == 0 && shots.GetArrayLength() == 3
            && stages.TryGetProperty("video_bible.v1", out var bible) && bible.ValueKind == JsonValueKind.Object
            && stages.TryGetProperty("keyframe_kit.v1", out var kit) && kit.ValueKind == JsonValueKind.Object
            && stages.TryGetProperty("script.v1", out var script) && script.ValueKind == JsonValueKind.Object
            && shots.EnumerateArray().All(shot => Text(shot, "render_intent") == "GENERATIVE_VIDEO");
        if (v2Candidate)
        {
            eligible.AddRange(shots.EnumerateArray().Select(shot => Text(shot, "shot_id")));
        }
        _requiresFullV2Batch = v2Candidate;
        _creativeJobId = package.CreativeJobId;
        _keyframeKitDigest = v2Candidate ? Text(kit, "kit_digest") : string.Empty;
        // 01. P0 完整计划只涵盖三镜头、四秒、横屏的已封存候选。
        KeyframeInstructions = v2Candidate ? ReadKeyframeInstructions(stages, eligible)
            : Array.Empty<ReferenceKeyframeInstruction>();
        _p0PlanCandidate = v2Candidate && KeyframeInstructions.Count == 3
            && stages.TryGetProperty("creative_brief.v1", out var brief)
            && Text(brief, "output_profile_id") == "video.landscape.v1"
            && shots.EnumerateArray().All(shot => shot.TryGetProperty("duration_seconds", out var duration)
                && duration.ValueKind == JsonValueKind.Number && duration.TryGetDouble(out var seconds) && seconds == 4);
        _gateway = gateway;
        _stager = stager;
        GoalId = continuation.GoalId;
        CreativePackageId = package.CreativePackageId;
        CreativePackageDigest = package.PackageDigest;
        EligibleShots = eligible.ToArray();
        _eligibleShots = new HashSet<string>(eligible, StringComparer.Ordinal);
    }

    public string GoalId { get; }
    public string CreativePackageId { get; }
    public string CreativePackageDigest { get; }
    public ObservableCollection<ReferencePreviewItem> Items { get; } = new();
    public ObservableCollection<ReferenceObservedCandidate> ObservedCandidates { get; } = new();
    public string[] EligibleShots { get; }
    public IReadOnlyList<ReferenceKeyframeInstruction> KeyframeInstructions { get; }
    public bool UserConfirmsPreviewAndRights
    {
        get => _consent;
        set
        {
            if (!CanEdit || !SetProperty(ref _consent, value)) return;
            RaisePropertyChanged(nameof(CanSubmit));
        }
    }
    public bool IsBusy => Volatile.Read(ref _operation) != 0;
    public bool CanEdit => !IsBusy && _frozenRequest is null;
    public bool CanLoadObservedCandidates => CanEdit && _p0PlanCandidate;
    public bool CanSubmit => !IsBusy && _initialReceipt is null && _consent && Items.Count > 0
        && (!_requiresFullV2Batch || Items.Count == _eligibleShots.Count);
    public bool CanRefresh => !IsBusy && _initialReceipt is not null;
    public ProductionJobRecord? CreatedProductionJob
    {
        get => _createdProductionJob;
        private set => SetProperty(ref _createdProductionJob, value);
    }
    public bool CanCreateReviewedPlan => !IsBusy && _p0PlanCandidate
        && _gateway is IReviewedThreeShotPlanGateway && _approvalFresh
        && Receipt is { Status: "Approved" } receipt && receipt.ExpiresAt > DateTimeOffset.UtcNow
        && receipt.References.Length == 3 && CreatedProductionJob is null;
    public string StatusText { get => _statusText; private set => SetProperty(ref _statusText, value); }
    public ReferenceBatchReceipt? Receipt { get => _receipt; private set => SetProperty(ref _receipt, value); }

    // 01. 校验本地候选清单的完整身份；只显示元数据，绝不自动 Stage 或批准。
    public async Task LoadObservedCandidatesAsync(string manifestPath, CancellationToken cancellationToken = default)
    {
        if (!CanLoadObservedCandidates) throw new InvalidDataException("KEYFRAME_OBSERVATION_NOT_ELIGIBLE");
        if (!Enter()) throw new InvalidOperationException("REFERENCE_OPERATION_BUSY");
        try
        {
            var info = new FileInfo(manifestPath);
            if (!info.Exists || info.Length is <= 0 or > 1024 * 1024)
                throw new InvalidDataException("KEYFRAME_CANDIDATE_MANIFEST_SIZE_INVALID");
            var raw = await File.ReadAllBytesAsync(manifestPath, cancellationToken);
            if (raw.LongLength != info.Length)
                throw new InvalidDataException("KEYFRAME_CANDIDATE_MANIFEST_CHANGED");
            using var document = JsonDocument.Parse(raw, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 24
            });
            var root = document.RootElement;
            RequireDistinctJsonProperties(root);
            if (Text(root, "schema") != "picotoo.local-keyframe-output-candidates.v1"
                || Text(root, "creative_package_id") != CreativePackageId
                || Text(root, "creative_package_sha256") != CreativePackageDigest
                || Text(root, "keyframe_kit_digest") != _keyframeKitDigest
                || !Bool(root, "recorded_image_bytes_observed")
                || Bool(root, "candidate_files_staged") || Bool(root, "reference_approved")
                || Bool(root, "source_rights_confirmed")
                || Number(root, "gpu_post") != 0
                || Text(root, "review_status") != "NEEDS_HUMAN_REVIEW"
                || !root.TryGetProperty("shots", out var shots)
                || shots.ValueKind != JsonValueKind.Array || shots.GetArrayLength() != 3)
                throw new InvalidDataException("KEYFRAME_OBSERVATION_CONTEXT_INVALID");
            var parsed = new List<ReferenceObservedCandidate>();
            var seenPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var index = 0;
            foreach (var shot in shots.EnumerateArray())
            {
                var shotId = Text(shot, "shot_id");
                if (shotId != EligibleShots[index] || Number(shot, "order") != index + 1
                    || !IsDigest(Text(shot, "prepared_graph_sha256"))
                    || !IsIdentifier(Text(shot, "prompt_id"))
                    || !shot.TryGetProperty("selected_reference", out var selected)
                    || selected.ValueKind != JsonValueKind.Null
                    || !shot.TryGetProperty("candidates", out var candidates)
                    || candidates.ValueKind != JsonValueKind.Array
                    || candidates.GetArrayLength() is < 1 or > 32)
                    throw new InvalidDataException("KEYFRAME_OBSERVATION_SHOT_INVALID");
                foreach (var item in candidates.EnumerateArray())
                {
                    var relative = Text(item, "output_relative_path");
                    var digest = Text(item, "sha256");
                    var bytes = Number(item, "bytes");
                    var width = Number(item, "width");
                    var height = Number(item, "height");
                    if (!SafeObservedRelativePath(relative) || !seenPaths.Add(relative)
                        || !IsDigest(digest) || bytes is <= 0 or > ReferencePreviewSnapshotStager.MaxBytes
                        || width is < 1 or > 8192 || height is < 1 or > 8192
                        || !Bool(item, "image_container_crc_verified")
                        || Bool(item, "pixels_decoded") || Text(item, "visual_review") != "UNREVIEWED")
                        throw new InvalidDataException("KEYFRAME_OBSERVATION_IMAGE_INVALID");
                    parsed.Add(new(shotId, relative, digest, bytes, (int)width, (int)height,
                        Text(shot, "prompt_id")));
                }
                index++;
            }
            ObservedCandidates.Clear();
            foreach (var observed in parsed) ObservedCandidates.Add(observed);
            StatusText = "已读取本地首帧候选清单；图片尚未选择、授权或导入，请逐张核验。";
        }
        catch
        {
            ObservedCandidates.Clear();
            StatusText = "候选清单未通过核验，未导入参考图或发送审批。";
            throw;
        }
        finally { Exit(); }
    }

    // 02. 用户明确选择一张本地生成图片，并提供许可摘要时，才调用已有可信快照管线。
    public async Task AddObservedCandidateAsync(ReferenceObservedCandidate observed,
        string comfyOutputRoot, string licensedSourceDigest, CancellationToken cancellationToken = default)
    {
        if (!CanEdit || observed is null || !ObservedCandidates.Contains(observed)
            || !IsDigest(licensedSourceDigest) || !Path.IsPathFullyQualified(comfyOutputRoot))
            throw new InvalidDataException("KEYFRAME_OBSERVED_RIGHTS_OR_SCOPE_REQUIRED");
        var path = ProductionLocalEnvironment.ResolveUnderRoot(
            comfyOutputRoot, observed.OutputRelativePath, true);
        ProductionLocalEnvironment.AssertNoLinkEscape(comfyOutputRoot, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
            || new FileInfo(path).Length != observed.Bytes
            || await ProductionLocalEnvironment.Sha256FileAsync(path, cancellationToken) != observed.Sha256)
            throw new InvalidDataException("KEYFRAME_OBSERVED_IMAGE_CHANGED");
        await AddAsync(observed.ShotId, path, "LICENSED", licensedSourceDigest, cancellationToken);
        var selected = Items.SingleOrDefault(x => x.ShotId == observed.ShotId);
        if (selected is null || selected.Sha256 != observed.Sha256 || selected.Bytes != observed.Bytes)
        {
            Remove(observed.ShotId);
            throw new InvalidDataException("KEYFRAME_OBSERVED_SNAPSHOT_MISMATCH");
        }
        // 03. 保持勾选框默认未确认，等待独立的预览和许可确认。
    }

    private static long Number(JsonElement element, string key)
    {
        if (!element.TryGetProperty(key, out var value)
            || value.ValueKind != JsonValueKind.Number || !value.TryGetInt64(out var parsed))
            throw new InvalidDataException("KEYFRAME_OBSERVATION_FIELD_INVALID");
        return parsed;
    }

    private static bool Bool(JsonElement element, string key)
    {
        if (!element.TryGetProperty(key, out var value)
            || value.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw new InvalidDataException("KEYFRAME_OBSERVATION_FIELD_INVALID");
        return value.GetBoolean();
    }

    private static bool SafeObservedRelativePath(string value) =>
        value is { Length: >= 1 and <= 240 }
        && !value.StartsWith("/", StringComparison.Ordinal)
        && !value.Contains('\\') && !value.Contains(':')
        && value.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
        && value.Split('/').All(part => part.Length is >= 1 and <= 100
            && part is not ("." or "..") && !part.EndsWith(' ') && !part.EndsWith('.')
            && part.All(ch => ch >= ' ' && ch != '\u007f'));

    private static void RequireDistinctJsonProperties(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in element.EnumerateObject())
            {
                if (!names.Add(field.Name)) throw new InvalidDataException("KEYFRAME_JSON_DUPLICATE_KEY");
                RequireDistinctJsonProperties(field.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray()) RequireDistinctJsonProperties(item);
        }
    }

    public async Task AddAsync(string shotId, string sourcePath, string sourceReference, string? sourceDigest,
        CancellationToken cancellationToken = default)
    {
        AssertEditable();
        if (!_eligibleShots.Contains(shotId)
            || sourceReference is not "USER_SUPPLIED" and not "LICENSED"
            || (sourceReference == "LICENSED" && !IsDigest(sourceDigest))
            || (!_snapshots.ContainsKey(shotId) && Items.Count >= 12))
            throw new InvalidDataException("REFERENCE_SELECTION_INVALID");
        if (!Enter()) throw new InvalidOperationException("REFERENCE_OPERATION_BUSY");
        try
        {
            var snapshot = await _stager.StageAsync(sourcePath, shotId, cancellationToken);
            var bytes = await _stager.ReadVerifiedAsync(snapshot, cancellationToken);
            var preview = await DecodePreviewAsync(bytes, snapshot.Format, cancellationToken);
            var item = new ReferencePreviewItem(shotId, snapshot.Sha256, snapshot.Bytes, snapshot.InputRelativePath,
                sourceReference, sourceReference == "USER_SUPPLIED" ? snapshot.Sha256 : sourceDigest!, preview);
            if (_snapshots.TryGetValue(shotId, out var previous)) Items.Remove(previous.Item);
            _snapshots[shotId] = (snapshot, item);
            Items.Add(item);
            _consent = false;
            RaisePropertyChanged(nameof(UserConfirmsPreviewAndRights));
            StatusText = "请查看每张预览，并明确确认预览与使用权后申请审批。";
        }
        catch { StatusText = "无法验证所选图片；请检查格式、大小和使用权声明。"; throw; }
        finally { Exit(); }
    }

    public void Remove(string shotId)
    {
        AssertEditable();
        if (_snapshots.Remove(shotId, out var previous)) Items.Remove(previous.Item);
        _consent = false;
        RaisePropertyChanged(nameof(UserConfirmsPreviewAndRights));
        NotifyState();
    }

    public async Task SubmitAsync(CancellationToken cancellationToken = default)
    {
        if (_initialReceipt is not null) { await RefreshAsync(cancellationToken); return; }
        if (!Enter()) return;
        try
        {
            if (!_consent) throw new InvalidDataException("REFERENCE_EXPLICIT_CONSENT_REQUIRED");
            // ── The new v2 Core contract requires all three trusted shot/image claims.
            if (_requiresFullV2Batch && Items.Count != _eligibleShots.Count)
                throw new InvalidDataException("REFERENCE_V2_FULL_COVERAGE_REQUIRED");
            var request = _frozenRequest ?? BuildRequest();
            ReferenceBatchValidation.ValidateRequest(request);
            await VerifySnapshotsAsync(request, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            // Freeze before transport: a timeout/cancellation cannot prove that Core did not accept the POST.
            _frozenRequest ??= request;
            NotifyState();
            var receipt = await _gateway.RegisterReferenceBatchAsync(request,
                ReferenceBatchValidation.IdempotencyKey(request), cancellationToken);
            ReferenceBatchValidation.ValidateReceipt(request, receipt);
            _initialReceipt = receipt with { References = receipt.References.ToArray() };
            Receipt = receipt;
            // 初次登记回执不作为生产依据；必须独立刷新正式批准状态。
            _approvalFresh = false;
            StatusText = "Core 已返回审批请求；请在现有审批中心查看并作出决定。";
        }
        catch { StatusText = _frozenRequest is null ? "未提交；请检查预览与使用权确认。"
            : "请求结果尚未验证；选择已锁定，重试将使用同一批次。"; throw; }
        finally { Exit(); }
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        var initial = _initialReceipt ?? throw new InvalidDataException("REFERENCE_RECEIPT_REQUIRED");
        var request = _frozenRequest ?? throw new InvalidDataException("REFERENCE_REQUEST_REQUIRED");
        if (!Enter()) return;
        try
        {
            ReferenceBatchValidation.ValidateRequest(request);
            await VerifySnapshotsAsync(request, cancellationToken);
            var fresh = await ReadBoundReceiptAsync(request, initial, cancellationToken);
            Receipt = fresh;
            _approvalFresh = fresh.Status == "Approved" && fresh.ExpiresAt > DateTimeOffset.UtcNow;
            StatusText = "已从 Core 刷新审批状态。";
        }
        catch { _approvalFresh = false; StatusText = "未能验证参考图或 Core 回执；未采纳新的审批状态。"; throw; }
        finally { Exit(); }
    }

    // 01. 此入口只生成完整三镜头计划；不得从刷新、审核成功或加载页面自动调用。
    public async Task CreateReviewedPlanAsync(CancellationToken cancellationToken = default)
    {
        if (!CanCreateReviewedPlan || _gateway is not IReviewedThreeShotPlanGateway production)
            throw new InvalidDataException("REFERENCE_APPROVED_FULL_BATCH_REQUIRED");
        var request = _frozenRequest ?? throw new InvalidDataException("REFERENCE_REQUEST_REQUIRED");
        var initial = _initialReceipt ?? throw new InvalidDataException("REFERENCE_RECEIPT_REQUIRED");
        if (!Enter()) return;
        try
        {
            _approvalFresh = false;
            await VerifySnapshotsAsync(request, cancellationToken);
            var fresh = await ReadBoundReceiptAsync(request, initial, cancellationToken);
            Receipt = fresh;
            if (fresh.Status != "Approved" || fresh.ExpiresAt <= DateTimeOffset.UtcNow)
                throw new InvalidDataException("REFERENCE_APPROVAL_NOT_CURRENT");
            if (!fresh.References.Select(x => x.ShotId).ToHashSet(StringComparer.Ordinal).SetEquals(_eligibleShots))
                throw new InvalidDataException("REFERENCE_V2_FULL_COVERAGE_REQUIRED");
            // 02. 固定批次与审批摘要构成重启可复现的幂等键；不使用随机重试 ID。
            var key = "reviewed-three-shot-v11-" + fresh.ApprovalId + "-" + fresh.ApprovalRequestDigest;
            var create = new ProductionJobCreateRequest(CreativePackageId,
                ProductionPanelViewModel.FixedProductionProfile, key);
            cancellationToken.ThrowIfCancellationRequested();
            var job = await production.CreateReviewedThreeShotV11Async(create, fresh.ApprovalId, cancellationToken);
            if (!Guid.TryParseExact(job.ProductionJobId, "D", out var jobId) || jobId == Guid.Empty
                || job.CreativePackageId != CreativePackageId || job.CreativePackageDigest != CreativePackageDigest
                || job.ProjectKey != "goal-" + GoalId || job.ProductionProfile != create.ProductionProfile
                || job.IdempotencyKey != key || !IsDigest(job.PlanDigest))
                throw new InvalidDataException("REFERENCE_PRODUCTION_JOB_MISMATCH");
            var plan = await production.ReadReviewedProductionPlanAsync(job.ProductionJobId, cancellationToken);
            ValidateCreatedPlan(job, plan, fresh);
            CreatedProductionJob = job;
            StatusText = "三镜头 v1.1 计划已创建并核对；尚未授权或启动 GPU，请进入原生产台。";
        }
        catch
        {
            // 未知 POST 结果不能宣称没有创建；刷新后同批次继续使用原幂等键。
            StatusText = "未取得可验证的生产计划；请刷新审批后重试同一批次，不会另建任务。";
            throw;
        }
        finally { Exit(); }
    }

    private async Task<ReferenceBatchReceipt> ReadBoundReceiptAsync(ReferenceBatchRequest request,
        ReferenceBatchReceipt initial, CancellationToken cancellationToken)
    {
        var fresh = await _gateway.GetReferenceBatchAsync(initial.ApprovalId, cancellationToken);
        ReferenceBatchValidation.ValidateReceipt(request, fresh);
        if (fresh.BatchId != initial.BatchId || fresh.ApprovalId != initial.ApprovalId
            || fresh.ApprovalRequestDigest != initial.ApprovalRequestDigest || fresh.ExpiresAt != initial.ExpiresAt
            || fresh.References.Any(reference => initial.References.Single(x => x.ShotId == reference.ShotId).AssetId != reference.AssetId))
            throw new InvalidDataException("REFERENCE_RECEIPT_IDENTITY_CHANGED");
        return fresh;
    }

    // 03. 展示成功之前，逐镜核对 Core 真实冻结计划和全部已批参考图。
    // 02. 显示原始首帧 Prompt 与检查清单，不替换 Core 判断。
    private static IReadOnlyList<ReferenceKeyframeInstruction> ReadKeyframeInstructions(JsonElement stages, List<string> shotIds)
    {
        if (!stages.TryGetProperty("keyframe_kit.v1", out var kit)
            || Text(kit, "schema_version") != "keyframe_kit.v1"
            || !IsDigest(Text(kit, "kit_digest")) || !IsDigest(Text(kit, "bible_digest"))
            || !kit.TryGetProperty("keyframes", out var frames)
            || frames.ValueKind != JsonValueKind.Array || frames.GetArrayLength() != 3)
            return Array.Empty<ReferenceKeyframeInstruction>();
        var items = new List<ReferenceKeyframeInstruction>();
        foreach (var frame in frames.EnumerateArray())
        {
            var index = items.Count;
            var id = Text(frame, "shot_id");
            var prompt = Text(frame, "still_prompt");
            if (id != shotIds[index] || prompt.Length is < 1 or > 5000
                || Text(frame, "approval_status") != "PENDING_HUMAN_REVIEW"
                || !frame.TryGetProperty("order", out var order)
                || order.ValueKind != JsonValueKind.Number || !order.TryGetInt32(out var number) || number != index + 1
                || !frame.TryGetProperty("review_checklist", out var checklist)
                || checklist.ValueKind != JsonValueKind.Array || checklist.GetArrayLength() is < 1 or > 20
                || checklist.EnumerateArray().Any(x => x.ValueKind != JsonValueKind.String
                    || string.IsNullOrWhiteSpace(x.GetString()) || x.GetString()!.Length > 500))
                return Array.Empty<ReferenceKeyframeInstruction>();
            items.Add(new(id, prompt, string.Join("\n", checklist.EnumerateArray().Select(x => x.GetString()))));
        }
        return items.AsReadOnly();
    }

    private void ValidateCreatedPlan(ProductionJobRecord job, ProductionPlanRecord plan, ReferenceBatchReceipt approved)
    {
        if (plan.SchemaVersion != "1.1" || plan.ProductionJobId != job.ProductionJobId
            || plan.CreativePackageId != CreativePackageId || plan.CreativePackageDigest != CreativePackageDigest
            || plan.ProjectKey != job.ProjectKey || plan.ProductionProfile != job.ProductionProfile
            || plan.OutputProfileId != "video.landscape.v1"
            || plan.TargetRuntimeMs != 12000 || plan.Tasks is not { Length: 3 }
            || !plan.Tasks.OrderBy(x => x.Order).Select(x => x.Order).SequenceEqual(P0ShotOrders)
            || !plan.Tasks.OrderBy(x => x.Order).Select(x => x.ShotId).SequenceEqual(EligibleShots))
            throw new InvalidDataException("REFERENCE_PRODUCTION_PLAN_MISMATCH");
        // 03. 复用现有执行器的 canonical JSON 摘要规则。
        var digest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(plan)!))).ToLowerInvariant();
        if (digest != job.PlanDigest) throw new InvalidDataException("REFERENCE_PRODUCTION_PLAN_DIGEST_MISMATCH");
        var taskIds = new HashSet<string>(StringComparer.Ordinal);
        foreach (var task in plan.Tasks)
        {
            var source = approved.References.Single(x => x.ShotId == task.ShotId);
            var asset = task.ReferenceAsset;
            if (string.IsNullOrWhiteSpace(task.ProductionTaskId) || !taskIds.Add(task.ProductionTaskId)
                || task.RenderIntent != "IMAGE_TO_VIDEO" || task.ExecutionDisposition != "Executable"
                || task.WorkflowId != ComfyWorkflowTemplateValidator.I2VWorkflowId
                || task.Width != 832 || task.Height != 480 || task.Fps != 24
                || task.FrameCount != 97 || task.TargetDurationMs != 4000 || asset is null
                || asset.SchemaVersion != "reference_asset.v1" || asset.AssetId != source.AssetId
                || asset.GoalId != GoalId || asset.CreativeJobId != _creativeJobId || asset.CreativePackageId != CreativePackageId
                || asset.CreativePackageDigest != CreativePackageDigest
                || asset.ProductionJobId != job.ProductionJobId || asset.ProductionTaskId != task.ProductionTaskId
                || asset.ShotId != task.ShotId || asset.ApprovalId != approved.ApprovalId
                || asset.ApprovalRequestDigest != approved.ApprovalRequestDigest
                || asset.InputRelativePath != source.InputRelativePath || task.TrustedInputAssetRef != source.InputRelativePath
                || asset.Sha256 != source.Sha256 || asset.Bytes != source.Bytes
                || asset.SourceReference != source.SourceReference || asset.SourceDigest != source.SourceDigest
                || asset.RightsScope != "wan22.i2v.production.v1")
                throw new InvalidDataException("REFERENCE_PRODUCTION_SHOT_MISMATCH");
        }
    }

    private ReferenceBatchRequest BuildRequest()
    {
        if (Items.Count != _snapshots.Count || Items.Any(item => !_snapshots.TryGetValue(item.ShotId, out var stored)
            || stored.Item != item)) throw new InvalidDataException("REFERENCE_PREVIEW_SELECTION_CHANGED");
        return new ReferenceBatchRequest("reference_batch.v1", GoalId, CreativePackageId, CreativePackageDigest,
            Items.OrderBy(x => x.ShotId, StringComparer.Ordinal).Select(x => new ReferenceCandidate(x.ShotId,
                x.InputRelativePath, x.Sha256, x.Bytes, x.SourceReference, x.SourceDigest, "wan22.i2v.production.v1")).ToArray(), true);
    }

    private async Task VerifySnapshotsAsync(ReferenceBatchRequest request, CancellationToken cancellationToken)
    {
        if (Items.Count != request.SelectedReferences.Length || Items.Count != _snapshots.Count)
            throw new InvalidDataException("REFERENCE_PREVIEW_SELECTION_CHANGED");
        foreach (var reference in request.SelectedReferences)
        {
            if (!_snapshots.TryGetValue(reference.ShotId, out var stored) || !Items.Contains(stored.Item)
                || stored.Snapshot.InputRelativePath != reference.InputRelativePath
                || stored.Snapshot.Sha256 != reference.Sha256 || stored.Snapshot.Bytes != reference.Bytes)
                throw new InvalidDataException("REFERENCE_PREVIEW_SELECTION_CHANGED");
            _ = await _stager.ReadVerifiedAsync(stored.Snapshot, cancellationToken);
        }
    }

    private void AssertEditable()
    {
        if (!CanEdit) throw new InvalidDataException("REFERENCE_SELECTION_LOCKED");
    }
    private bool Enter()
    {
        if (Interlocked.CompareExchange(ref _operation, 1, 0) != 0) return false;
        NotifyState();
        return true;
    }
    private void Exit() { Volatile.Write(ref _operation, 0); NotifyState(); }
    private void NotifyState()
    {
        RaisePropertyChanged(nameof(IsBusy));
        RaisePropertyChanged(nameof(CanEdit));
        RaisePropertyChanged(nameof(CanLoadObservedCandidates));
        RaisePropertyChanged(nameof(CanSubmit));
        RaisePropertyChanged(nameof(CanRefresh));
        RaisePropertyChanged(nameof(CanCreateReviewedPlan));
    }
    private static string Text(JsonElement element, string property) => element.ValueKind == JsonValueKind.Object
        && element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : string.Empty;
    private static bool IsDigest(string? value) => value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static bool IsIdentifier(string? value) => Guid.TryParseExact(value, "D", out var id) && id != Guid.Empty;

    public static async Task<BitmapSource> DecodePreviewAsync(byte[] bytes, string extension,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        ArgumentNullException.ThrowIfNull(extension);
        if (bytes.Length is <= 0 or > ReferencePreviewSnapshotStager.MaxBytes)
            throw new InvalidDataException("REFERENCE_IMAGE_SIZE_INVALID");
        if (extension.TrimStart('.').Equals("webp", StringComparison.OrdinalIgnoreCase))
            return DecodeWebpPreview(bytes, cancellationToken);
        var codec = extension.TrimStart('.').ToLowerInvariant() switch
        {
            "png" => BitmapDecoder.PngDecoderId,
            "jpg" or "jpeg" => BitmapDecoder.JpegDecoderId,
            _ => throw new InvalidDataException("REFERENCE_IMAGE_FORMAT_INVALID")
        };
        try
        {
            using var stream = new InMemoryRandomAccessStream();
            using (var writer = new DataWriter(stream))
            {
                writer.WriteBytes(bytes);
                await writer.StoreAsync().AsTask(cancellationToken);
                writer.DetachStream();
            }
            stream.Seek(0);
            var decoder = await BitmapDecoder.CreateAsync(codec, stream).AsTask(cancellationToken);
            if (decoder.DecoderInformation.CodecId != codec || decoder.FrameCount != 1
                || decoder.PixelWidth is 0 or > 8192 || decoder.PixelHeight is 0 or > 8192
                || (ulong)decoder.PixelWidth * decoder.PixelHeight > 16_000_000)
                throw new InvalidDataException("REFERENCE_IMAGE_METADATA_INVALID");
            var scale = Math.Min(1.0, 384.0 / Math.Max(decoder.PixelWidth, decoder.PixelHeight));
            var width = Math.Max(1, (int)(decoder.PixelWidth * scale));
            var height = Math.Max(1, (int)(decoder.PixelHeight * scale));
            var transform = new BitmapTransform { ScaledWidth = (uint)width, ScaledHeight = (uint)height,
                InterpolationMode = BitmapInterpolationMode.Fant };
            var pixels = await decoder.GetPixelDataAsync(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied,
                transform, ExifOrientationMode.IgnoreExifOrientation, ColorManagementMode.DoNotColorManage).AsTask(cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            var preview = BitmapSource.Create(width, height, 96, 96, PixelFormats.Pbgra32, null,
                pixels.DetachPixelData(), checked(width * 4));
            preview.Freeze();
            return preview;
        }
        catch (COMException exception) { throw new InvalidDataException("REFERENCE_IMAGE_DECODE_FAILED", exception); }
    }

    private static BitmapSource DecodeWebpPreview(byte[] bytes, CancellationToken cancellationToken)
    {
        // Portable bundled CPU WebP decoding remains isolated to preview-only library;
        // the Mac Core client and Desktop tray keep their frozen dependency contracts.
        var decoded = ReferencePreviewWebpDecoder.Decode(bytes, cancellationToken);
        BitmapSource preview = BitmapSource.Create(decoded.Width, decoded.Height, 96, 96,
            PixelFormats.Pbgra32, null, decoded.Pixels, decoded.Stride);
        var scale = Math.Min(1.0, 384.0 / Math.Max(decoded.Width, decoded.Height));
        if (scale < 1.0) preview = new TransformedBitmap(preview, new ScaleTransform(scale, scale));
        preview.Freeze();
        return preview;
    }

    public static async Task ValidateImageAsync(byte[] bytes, string extension, CancellationToken cancellationToken)
        => _ = await DecodePreviewAsync(bytes, extension, cancellationToken);
}
