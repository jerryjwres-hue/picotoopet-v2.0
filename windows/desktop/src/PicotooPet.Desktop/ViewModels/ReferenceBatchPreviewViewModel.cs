using System.Collections.ObjectModel;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;
using BitmapDecoder = Windows.Graphics.Imaging.BitmapDecoder;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.ViewModels;

public sealed record ReferencePreviewItem(string ShotId, string Sha256, long Bytes,
    string InputRelativePath, string SourceReference, string SourceDigest, BitmapSource Preview);

/// <summary>Local preview and explicit request for existing Core approvals; never grants execution permission.</summary>
public sealed class ReferenceBatchPreviewViewModel : ObservableObject
{
    private readonly IReferenceBatchGateway _gateway;
    private readonly ReferencePreviewSnapshotStager _stager;
    private readonly Dictionary<string, (ReferencePreviewSnapshot Snapshot, ReferencePreviewItem Item)> _snapshots = new(StringComparer.Ordinal);
    private ReferenceBatchRequest? _frozenRequest;
    private ReferenceBatchReceipt? _initialReceipt;
    private ReferenceBatchReceipt? _receipt;
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
            || !Guid.TryParse(continuation.GoalId, out _) || !Guid.TryParse(package.CreativePackageId, out _)
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
        _gateway = gateway;
        _stager = stager;
        GoalId = continuation.GoalId;
        CreativePackageId = package.CreativePackageId;
        CreativePackageDigest = package.PackageDigest;
        EligibleShots = eligible.ToArray();
    }

    public string GoalId { get; }
    public string CreativePackageId { get; }
    public string CreativePackageDigest { get; }
    public ObservableCollection<ReferencePreviewItem> Items { get; } = new();
    public string[] EligibleShots { get; }
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
    public bool CanSubmit => !IsBusy && _initialReceipt is null && _consent && Items.Count > 0;
    public bool CanRefresh => !IsBusy && _initialReceipt is not null;
    public string StatusText { get => _statusText; private set => SetProperty(ref _statusText, value); }
    public ReferenceBatchReceipt? Receipt { get => _receipt; private set => SetProperty(ref _receipt, value); }

    public async Task AddAsync(string shotId, string sourcePath, string sourceReference, string? sourceDigest,
        CancellationToken cancellationToken = default)
    {
        AssertEditable();
        if (!EligibleShots.Contains(shotId, StringComparer.Ordinal)
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
            var fresh = await _gateway.GetReferenceBatchAsync(initial.ApprovalId, cancellationToken);
            ReferenceBatchValidation.ValidateReceipt(request, fresh);
            if (fresh.BatchId != initial.BatchId || fresh.ApprovalId != initial.ApprovalId
                || fresh.ApprovalRequestDigest != initial.ApprovalRequestDigest || fresh.ExpiresAt != initial.ExpiresAt
                || fresh.References.Any(reference => initial.References.Single(x => x.ShotId == reference.ShotId).AssetId != reference.AssetId))
                throw new InvalidDataException("REFERENCE_RECEIPT_IDENTITY_CHANGED");
            Receipt = fresh;
            StatusText = "已从 Core 刷新审批状态。";
        }
        catch { StatusText = "未能验证参考图或 Core 回执；未采纳新的审批状态。"; throw; }
        finally { Exit(); }
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
        RaisePropertyChanged(nameof(CanSubmit));
        RaisePropertyChanged(nameof(CanRefresh));
    }
    private static string Text(JsonElement element, string property) => element.ValueKind == JsonValueKind.Object
        && element.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString()! : string.Empty;
    private static bool IsDigest(string? value) => value is { Length: 64 } && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');

    public static async Task<BitmapSource> DecodePreviewAsync(byte[] bytes, string extension,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        ArgumentNullException.ThrowIfNull(extension);
        if (bytes.Length is <= 0 or > ReferencePreviewSnapshotStager.MaxBytes)
            throw new InvalidDataException("REFERENCE_IMAGE_SIZE_INVALID");
        var codec = extension.TrimStart('.').ToLowerInvariant() switch
        {
            "png" => BitmapDecoder.PngDecoderId,
            "jpg" or "jpeg" => BitmapDecoder.JpegDecoderId,
            "webp" => BitmapDecoder.WebpDecoderId,
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
            var decoder = await BitmapDecoder.CreateAsync(stream).AsTask(cancellationToken);
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

    public static async Task ValidateImageAsync(byte[] bytes, string extension, CancellationToken cancellationToken)
        => _ = await DecodePreviewAsync(bytes, extension, cancellationToken);
}
