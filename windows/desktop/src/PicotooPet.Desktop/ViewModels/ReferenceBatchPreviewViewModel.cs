using System.Collections.ObjectModel;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;

#pragma warning disable CA1822 // Compile-only RED scaffold, replaced after native behavioral failure.

namespace PicotooPet.Desktop.ViewModels;

public sealed record ReferencePreviewItem(string ShotId, string Sha256, long Bytes,
    string InputRelativePath, string SourceReference, string SourceDigest, BitmapSource Preview);

public sealed class ReferenceBatchPreviewViewModel : ObservableObject
{
    public ReferenceBatchPreviewViewModel(IReferenceBatchGateway gateway, ReferencePreviewSnapshotStager stager,
        GoalVideoContinuationRecord continuation, CreativePackageRecord package) { }
    public ObservableCollection<ReferencePreviewItem> Items { get; } = new();
    public string[] EligibleShots { get; } = Array.Empty<string>();
    public bool UserConfirmsPreviewAndRights { get; set; }
    public bool IsBusy => false;
    public bool CanEdit => true;
    public bool CanSubmit => false;
    public bool CanRefresh => false;
    public string StatusText => string.Empty;
    public ReferenceBatchReceipt? Receipt => null;
    public Task AddAsync(string shotId, string sourcePath, string sourceReference, string? sourceDigest,
        CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public Task SubmitAsync(CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public Task RefreshAsync(CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public void Remove(string shotId) => throw new NotImplementedException();
    public static Task<BitmapSource> DecodePreviewAsync(byte[] bytes, string extension,
        CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public static async Task ValidateImageAsync(byte[] bytes, string extension, CancellationToken cancellationToken)
        => _ = await DecodePreviewAsync(bytes, extension, cancellationToken);
}
