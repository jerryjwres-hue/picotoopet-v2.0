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

public sealed record ReferenceKeyframeInstruction(
    string ShotId, string StillPrompt, string ReviewChecklist, string SceneId, string CameraFraming,
    string OpeningState, string ClosingState, string HandoffToNext);

// 只读工作单只反映本地构图缺口，不是资产导入、真实图片审核或 GPU 授权。
public sealed record ReferenceCompositionWorkItem(
    string ShotId, string Status, string ExistingFilename, string StillPrompt,
    string ReviewChecklist, string SceneId, string CameraFraming,
    string OpeningState, string ClosingState, string HandoffToNext);

// 只读候选是历史输出观测，不是 Producer 授权、身份资产或使用许可。
public sealed record ReferenceObservedCandidate(string ShotId, string OutputRelativePath,
    string Sha256, long Bytes, int Width, int Height, string PromptId,
    BitmapSource? Preview = null);

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
        _keyframeKitDigest = v2Candidate && stages.TryGetProperty("keyframe_kit.v1", out var pinnedKit)
            ? Text(pinnedKit, "kit_digest") : string.Empty;
        // 01. P0 完整计划只涵盖三镜头、四秒、横屏的已封存候选。
        KeyframeInstructions = v2Candidate ? ReadKeyframeInstructions(stages, eligible)
            : Array.Empty<ReferenceKeyframeInstruction>();
        _p0PlanCandidate = v2Candidate && KeyframeInstructions.Count == 3
            && stages.TryGetProperty("creative_brief.v1", out var brief)
            && Text(brief, "output_profile_id") == "video.landscape.v1"
            && shots.EnumerateArray().All(shot => shot.TryGetProperty("duration_seconds", out var duration)
                && duration.ValueKind == JsonValueKind.Number && duration.TryGetDouble(out var seconds) && seconds == 4);
        // 02. A frozen Kit is the permanent trusted source for these three
        //     briefs; an optional local report can replace only observation status.
        ResetCompositionWorkOrdersToFrozen();
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
    public ObservableCollection<ReferenceCompositionWorkItem> CompositionWorkOrders { get; } = new();
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
    public bool CanLoadCompositionWorkOrder => CanEdit && _p0PlanCandidate;
    public bool CanResumeReferenceBatch => CanLoadObservedCandidates
        && _initialReceipt is null && Items.Count == 0;
    public bool CanSubmit => !IsBusy && _initialReceipt is null && _consent && Items.Count > 0
        && (!_requiresFullV2Batch || (Items.Count == _eligibleShots.Count
            && Items.Select(x => x.Sha256).Distinct(StringComparer.Ordinal).Count() == Items.Count));
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

    // 01. 从正式 Core 已存在的审批 ID 恢复三个本地快照，而非重新申请审批。
    //     这仅恢复观察态；即使 Core 回报 Approved，也必须显式刷新再创建 Plan。
    public async Task ResumeReferenceBatchAsync(string approvalId, CancellationToken cancellationToken = default)
    {
        if (!CanResumeReferenceBatch || !IsIdentifier(approvalId))
            throw new InvalidDataException("REFERENCE_RESUME_CONTEXT_INVALID");
        if (!Enter()) throw new InvalidOperationException("REFERENCE_OPERATION_BUSY");
        try
        {
            var receipt = await _gateway.GetReferenceBatchAsync(approvalId, cancellationToken);
            if (receipt.ApprovalId != approvalId || receipt.GoalId != GoalId
                || receipt.CreativePackageId != CreativePackageId
                || receipt.CreativePackageDigest != CreativePackageDigest
                || receipt.References.Length != 3
                || !receipt.References.Select(x => x.ShotId)
                    .ToHashSet(StringComparer.Ordinal).SetEquals(_eligibleShots))
                throw new InvalidDataException("REFERENCE_RESUME_SCOPE_INVALID");

            // 02. 从 Core 回执重建只读请求，但不调用 Register/POST。
            var references = receipt.References
                .OrderBy(x => Array.IndexOf(EligibleShots, x.ShotId))
                .ToArray();
            var reconstructed = new ReferenceBatchRequest(
                "reference_batch.v1", GoalId, CreativePackageId, CreativePackageDigest,
                references.Select(x => new ReferenceCandidate(
                    x.ShotId, x.InputRelativePath, x.Sha256, x.Bytes,
                    x.SourceReference, x.SourceDigest, "wan22.i2v.production.v1")).ToArray(),
                true);
            ReferenceBatchValidation.ValidateReceipt(reconstructed, receipt);

            // 03. 只有所有已登记图片通过既有 CAS 检查与实际像素解码，才发布恢复态。
            var validated = new List<(ReferencePreviewSnapshot Snapshot, ReferencePreviewItem Item)>();
            foreach (var row in references)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var format = Path.GetExtension(row.InputRelativePath).ToLowerInvariant();
                if (format is not (".png" or ".jpg" or ".webp"))
                    throw new InvalidDataException("REFERENCE_RESUME_FORMAT_INVALID");
                var snapshot = new ReferencePreviewSnapshot(row.InputRelativePath, row.Sha256, row.Bytes, format);
                var bytes = await _stager.ReadVerifiedAsync(snapshot, cancellationToken);
                var preview = await DecodePreviewAsync(bytes, format, cancellationToken);
                validated.Add((snapshot, new ReferencePreviewItem(
                    row.ShotId, row.Sha256, row.Bytes, row.InputRelativePath,
                    row.SourceReference, row.SourceDigest, preview)));
            }
            foreach (var entry in validated)
            {
                _snapshots.Add(entry.Item.ShotId, entry);
                Items.Add(entry.Item);
            }
            _frozenRequest = reconstructed;
            _initialReceipt = receipt with { References = receipt.References.ToArray() };
            Receipt = receipt;
            _approvalFresh = false;
            _consent = false;
            RaisePropertyChanged(nameof(UserConfirmsPreviewAndRights));
            StatusText = "既有三镜头批次已恢复（仅本地只读），请先刷新 Core 审批状态；不会重复注册。";
        }
        catch
        {
            // 04. 失败时绝不保留半批次或错误批准状态。
            _snapshots.Clear();
            Items.Clear();
            _frozenRequest = null;
            _initialReceipt = null;
            Receipt = null;
            _approvalFresh = false;
            StatusText = "恢复失败：审批身份或本地快照无法重新验证，未创建任何新任务。";
            throw;
        }
        finally { Exit(); }
    }

    // 04. 从既有 Qwen readiness JSON 读取三镜头工作单；保留原 WPF 审批路径。
    //     同一 Creative Package / Keyframe Kit 的字节指纹和原始 Prompt
    //     必须逐镜一致；此读取不碰 Core、磁盘快照、Comfy 或 GPU。
    public async Task LoadCompositionWorkOrderAsync(string reportPath,
        CancellationToken cancellationToken = default)
    {
        if (!CanLoadCompositionWorkOrder)
            throw new InvalidDataException("COMPOSITION_WORKORDER_NOT_ELIGIBLE");
        if (!Enter()) throw new InvalidOperationException("REFERENCE_OPERATION_BUSY");
        try
        {
            var file = new FileInfo(reportPath);
            if (!file.Exists || file.Length is <= 0 or > 1024 * 1024)
                throw new InvalidDataException("COMPOSITION_WORKORDER_SIZE_INVALID");
            var raw = await File.ReadAllBytesAsync(reportPath, cancellationToken);
            if (raw.LongLength != file.Length)
                throw new InvalidDataException("COMPOSITION_WORKORDER_CHANGED");
            using var document = JsonDocument.Parse(raw, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 24
            });
            var root = document.RootElement;
            RequireDistinctJsonProperties(root);
            if (Text(root, "schema") != "picotoo.qwen-reference-readiness.v1"
                || Text(root, "creative_package_sha256") != CreativePackageDigest
                || Text(root, "creative_kit_digest") != _keyframeKitDigest
                || Bool(root, "source_rights_confirmed")
                || Bool(root, "source_inputs_verified_for_production")
                || Bool(root, "production_authorized")
                || Number(root, "gpu_post") != 0
                || Text(root, "status") is not (
                    "BLOCKED_MISSING_REFERENCES" or "BLOCKED_INVALID_REFERENCE"
                    or "READY_FOR_OWNER_BINDING_REVIEW")
                || !root.TryGetProperty("composition_work_order", out var work)
                || Text(work, "schema") != "picotoo.qwen-local-composition-workorder.v1"
                || Text(work, "creative_kit_digest") != _keyframeKitDigest
                || Number(work, "shot_count") != 3
                || Bool(work, "source_workflow_modified")
                || Bool(work, "all_images_approved")
                || Number(work, "gpu_post") != 0
                || !work.TryGetProperty("items", out var items)
                || items.ValueKind != JsonValueKind.Array || items.GetArrayLength() != 3)
                throw new InvalidDataException("COMPOSITION_WORKORDER_CONTEXT_INVALID");

            var parsed = new List<ReferenceCompositionWorkItem>();
            foreach (var item in items.EnumerateArray())
            {
                var index = parsed.Count;
                var frozen = KeyframeInstructions[index];
                var prompt = Text(item, "creative_still_prompt");
                var promptDigest = Convert.ToHexStringLower(
                    SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(prompt)));
                var state = Text(item, "composition_status");
                var hasFilename = item.TryGetProperty("existing_input_filename", out var input)
                    && input.ValueKind == JsonValueKind.String;
                var name = hasFilename ? input.GetString()! : string.Empty;
                if (Text(item, "shot_id") != frozen.ShotId || Number(item, "order") != index + 1
                    || Text(item, "source") != "FROZEN_CREATIVE_KEYFRAME_KIT"
                    || prompt != frozen.StillPrompt
                    || Text(item, "creative_still_prompt_sha256") != promptDigest
                    || Text(item, "camera_framing") != frozen.CameraFraming
                    || Text(item, "scene_id") != frozen.SceneId
                    // 04. New Python reports may include actual Bible state
                    //     handoffs. If supplied, they must match frozen Core
                    //     data. Old reports without these keys remain read-only.
                    || (item.TryGetProperty("opening_state", out _)
                        && Text(item, "opening_state") != frozen.OpeningState)
                    || (item.TryGetProperty("closing_state", out _)
                        && Text(item, "closing_state") != frozen.ClosingState)
                    || (item.TryGetProperty("handoff_to_next", out _)
                        && Text(item, "handoff_to_next") != frozen.HandoffToNext)
                    || !item.TryGetProperty("review_checklist", out var checklist)
                    || checklist.ValueKind != JsonValueKind.Array
                    || string.Join("\n", checklist.EnumerateArray().Select(x => x.ValueKind ==
                        JsonValueKind.String ? x.GetString() : null)) != frozen.ReviewChecklist
                    || !Bool(item, "prompt_text_local_only")
                    || Bool(item, "new_image_created") || Bool(item, "owner_approved")
                    || state is not ("OBSERVED_UNAPPROVED" or "NEEDS_DISTINCT_COMPOSITION"
                        or "INVALID_REFERENCE" or "UNVERIFIED")
                    || (state == "OBSERVED_UNAPPROVED" && !hasFilename)
                    || (state != "OBSERVED_UNAPPROVED" && hasFilename)
                    || (hasFilename && (name.Length is < 1 or > 240 || name.Contains('\\')
                        || name.Contains(':') || name.StartsWith('/')
                        || name.Split('/').Any(part => part is "" or "." or ".."
                            || part.EndsWith(' ') || part.EndsWith('.')))))
                    throw new InvalidDataException("COMPOSITION_WORKORDER_SHOT_INVALID");
                parsed.Add(new(frozen.ShotId, state, name, frozen.StillPrompt,
                    frozen.ReviewChecklist, frozen.SceneId, frozen.CameraFraming,
                    frozen.OpeningState, frozen.ClosingState, frozen.HandoffToNext));
            }
            if (Text(root, "status") == "READY_FOR_OWNER_BINDING_REVIEW"
                && parsed.Any(x => x.Status != "OBSERVED_UNAPPROVED"))
                throw new InvalidDataException("COMPOSITION_WORKORDER_READY_CONFLICT");

            CompositionWorkOrders.Clear();
            foreach (var item in parsed) CompositionWorkOrders.Add(item);
            StatusText = "三镜头构图工作单已核对封存 Prompt；这只是本地状态，图片、来源权利和 Owner 审批均未获得认可。";
        }
        catch
        {
            // 03. Reject untrusted local report, but never erase the immutable
            //     Core-frozen brief or require an unrelated JSON just to resume.
            ResetCompositionWorkOrdersToFrozen();
            StatusText = "本地报告核验失败；已清除其观察结果，封存三镜头指令保留。未导入资产或申请审批。";
            throw;
        }
        finally { Exit(); }
    }

    // 04. Restoring the Core-frozen data never observes or approves a local image.
    //     Use this after rejecting a forged/stale optional Qwen status report.
    private void ResetCompositionWorkOrdersToFrozen()
    {
        CompositionWorkOrders.Clear();
        if (!_p0PlanCandidate) return;
        foreach (var instruction in KeyframeInstructions)
            CompositionWorkOrders.Add(new(
                instruction.ShotId, "UNVERIFIED", string.Empty, instruction.StillPrompt,
                instruction.ReviewChecklist, instruction.SceneId, instruction.CameraFraming,
                instruction.OpeningState, instruction.ClosingState, instruction.HandoffToNext));
    }

    // 05. 校验本地候选清单的完整身份；只显示元数据，绝不自动 Stage 或批准。
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
            // 01. PNG-embedded historyless evidence never receives a fake UUID.
            //     Only exact graph-bound offline bytes can reach human review.
            var provenance = Text(root, "history_provenance");
            var embedded = provenance == "PNG_EMBEDDED_NO_HISTORY";
            if (provenance is not ("" or "PNG_EMBEDDED_NO_HISTORY")
                || (embedded && Bool(root, "comfy_history_success_verified")))
                throw new InvalidDataException("KEYFRAME_OBSERVATION_PROVENANCE_INVALID");
            var parsed = new List<ReferenceObservedCandidate>();
            var seenPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var seenDigests = new HashSet<string>(StringComparer.Ordinal);
            var seenPrompts = new HashSet<string>(StringComparer.Ordinal);
            var index = 0;
            foreach (var shot in shots.EnumerateArray())
            {
                var shotId = Text(shot, "shot_id");
                var promptId = Text(shot, "prompt_id");
                if (!shot.TryGetProperty("prompt_id", out var promptValue)
                    || (embedded
                        ? promptValue.ValueKind != JsonValueKind.Null
                        : !IsIdentifier(promptId) || !seenPrompts.Add(promptId)))
                    throw new InvalidDataException("KEYFRAME_OBSERVATION_HISTORY_ID_INVALID");
                if (shotId != EligibleShots[index] || Number(shot, "order") != index + 1
                    || !IsDigest(Text(shot, "prepared_graph_sha256"))
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
                        || !IsDigest(digest) || !seenDigests.Add(digest)
                        || bytes is <= 0 or > ReferencePreviewSnapshotStager.MaxBytes
                        || width is < 1 or > 8192 || height is < 1 or > 8192
                        || width * height > 16_000_000
                        || !Bool(item, "image_container_crc_verified")
                        || (embedded && !Bool(item, "embedded_prompt_graph_verified"))
                        || Bool(item, "pixels_decoded") || Text(item, "visual_review") != "UNREVIEWED")
                        throw new InvalidDataException("KEYFRAME_OBSERVATION_IMAGE_INVALID");
                    parsed.Add(new(shotId, relative, digest, bytes, (int)width, (int)height,
                        promptId));
                }
                index++;
            }
            ObservedCandidates.Clear();
            foreach (var observed in parsed) ObservedCandidates.Add(observed);
            StatusText = embedded
                ? "已核验无历史 Prompt ID 的 PNG 内嵌图合同；未认证运行成功，仍需人工审片和许可。"
                : "已读取本地首帧候选清单；图片尚未选择、授权或导入，请逐张核验。";
        }
        catch
        {
            ObservedCandidates.Clear();
            StatusText = "候选清单未通过核验，未导入参考图或发送审批。";
            throw;
        }
        finally { Exit(); }
    }

    // 02. 同一输出根目录一次完成所有候选的字节重核与低分辨率缩略图。
    //     这里只读解码供视觉选择，不能产生身份、许可或生产 PASS。
    public async Task InspectObservedCandidatesAsync(string outputRoot, CancellationToken cancellationToken = default)
    {
        if (!CanLoadObservedCandidates || !Path.IsPathFullyQualified(outputRoot)
            || ObservedCandidates.Count is < 3 or > 96)
            throw new InvalidDataException("KEYFRAME_THUMBNAIL_CONTEXT_INVALID");
        if (!Enter()) throw new InvalidOperationException("REFERENCE_OPERATION_BUSY");
        try
        {
            var inspected = new List<ReferenceObservedCandidate>();
            foreach (var observed in ObservedCandidates)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var path = ProductionLocalEnvironment.ResolveUnderRoot(
                    outputRoot, observed.OutputRelativePath, true);
                ProductionLocalEnvironment.AssertNoLinkEscape(outputRoot, path);
                if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
                    || new FileInfo(path).Length != observed.Bytes)
                    throw new InvalidDataException("KEYFRAME_THUMBNAIL_FILE_CHANGED");
                // 03. 每次从真实磁盘字节重新计算哈希，不信任 manifest 声明。
                var bytes = await File.ReadAllBytesAsync(path, cancellationToken);
                if (bytes.LongLength != observed.Bytes
                    || Convert.ToHexStringLower(SHA256.HashData(bytes)) != observed.Sha256)
                    throw new InvalidDataException("KEYFRAME_THUMBNAIL_HASH_CHANGED");
                using var metadataStream = new MemoryStream(bytes, writable: false);
                var decoder = System.Windows.Media.Imaging.BitmapDecoder.Create(
                    metadataStream, BitmapCreateOptions.DelayCreation, BitmapCacheOption.OnDemand);
                if (decoder.Frames.Count != 1 || decoder.Frames[0].PixelWidth != observed.Width
                    || decoder.Frames[0].PixelHeight != observed.Height)
                    throw new InvalidDataException("KEYFRAME_THUMBNAIL_DIMENSIONS_CHANGED");
                using var thumbnailStream = new MemoryStream(bytes, writable: false);
                var thumbnail = new BitmapImage();
                thumbnail.BeginInit();
                thumbnail.CacheOption = BitmapCacheOption.OnLoad;
                thumbnail.DecodePixelWidth = 240;
                thumbnail.StreamSource = thumbnailStream;
                thumbnail.EndInit();
                thumbnail.Freeze();
                inspected.Add(observed with { Preview = thumbnail });
            }
            // 04. 全批校验后一次发布；任何单张失败不得留下部分可信外观。
            for (var index = 0; index < inspected.Count; index++)
                ObservedCandidates[index] = inspected[index];
            StatusText = "已读取并重核全部候选缩略图；仍需人工选择、确认来源许可和申请审批。";
        }
        catch
        {
            for (var index = 0; index < ObservedCandidates.Count; index++)
                ObservedCandidates[index] = ObservedCandidates[index] with { Preview = null };
            StatusText = "候选原图或路径已变化；清除预览，不接受候选图为有效来源。";
            throw;
        }
        finally { Exit(); }
    }

    // 05. 用户明确选择一张本地生成图片，并提供许可摘要时，才调用已有可信快照管线。
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
        && value[0] != '/'
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
            // 06. Only the sealed V2 three-shot path requires distinct
            //     composition contents; legacy reference batches stay intact.
            StatusText = _requiresFullV2Batch
                && Items.Select(x => x.Sha256).Distinct(StringComparer.Ordinal).Count() != Items.Count
                ? "不同镜头选中了相同图像内容，需更换独立构图；当前不能提交批量审批。"
                : "请查看每张预览，并明确确认预览与使用权后申请审批。";
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
            // 07. Direct callers cannot bypass a disabled WPF button and
            //     re-submit byte-identical images for different V2 shots.
            if (_requiresFullV2Batch && Items.Select(x => x.Sha256)
                    .Distinct(StringComparer.Ordinal).Count() != Items.Count)
                throw new InvalidDataException("REFERENCE_V2_DUPLICATE_IMAGE_BYTES");
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
        // 01. Real KeyframeSpec has camera_framing but scene_id lives in
        //     the Kit's shared locks. The video Bible carries actual shot
        //     opening/closing state and cut handoffs for continuity review.
        var lockedScene = kit.TryGetProperty("locks", out var locks)
            ? Text(locks, "scene_id") : string.Empty;
        JsonElement bibleShots = default;
        var hasBibleShots = stages.TryGetProperty("video_bible.v1", out var bible)
            && bible.ValueKind == JsonValueKind.Object
            && bible.TryGetProperty("shots", out bibleShots)
            && bibleShots.ValueKind == JsonValueKind.Array && bibleShots.GetArrayLength() == 3;
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
            var frameScene = Text(frame, "scene_id");
            // 02. Never let a shot-local claim override the immutable global
            //     scene lock; older synthetic/legacy kits may have only one.
            if (lockedScene.Length > 120 || (lockedScene.Length > 0
                && frameScene.Length > 0 && lockedScene != frameScene))
                return Array.Empty<ReferenceKeyframeInstruction>();
            var scene = lockedScene.Length > 0 ? lockedScene : frameScene;
            var camera = Text(frame, "camera_framing");
            if (scene.Length > 120 || camera.Length > 180)
                return Array.Empty<ReferenceKeyframeInstruction>();

            var opening = string.Empty;
            var closing = string.Empty;
            var handoff = string.Empty;
            if (hasBibleShots)
            {
                var shot = bibleShots[index];
                // 03. Continuity is an informational copy of the frozen
                //     Bible only, not a command inferred from a Qwen report.
                if (Text(shot, "shot_id") == id
                    && Text(shot, "scene_id") == scene
                    && shot.TryGetProperty("order", out var bibleOrder)
                    && bibleOrder.ValueKind == JsonValueKind.Number
                    && bibleOrder.TryGetInt32(out var ordinal) && ordinal == index + 1)
                {
                    var start = Text(shot, "opening_state");
                    var end = Text(shot, "closing_state");
                    var cut = Text(shot, "handoff_to_next");
                    if (start.Length is > 0 and <= 300 && end.Length is > 0 and <= 300
                        && cut is "CONTINUOUS" or "CUT_ON_ACTION" or "SCENE_CHANGE")
                    {
                        opening = start;
                        closing = end;
                        handoff = cut;
                    }
                }
            }
            items.Add(new(id, prompt,
                string.Join("\n", checklist.EnumerateArray().Select(x => x.GetString())),
                scene, camera, opening, closing, handoff));
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
        RaisePropertyChanged(nameof(CanLoadCompositionWorkOrder));
        RaisePropertyChanged(nameof(CanResumeReferenceBatch));
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
