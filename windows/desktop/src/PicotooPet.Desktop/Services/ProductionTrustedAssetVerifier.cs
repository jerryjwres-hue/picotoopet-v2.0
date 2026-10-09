using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

public sealed record ProductionVerifiedTrustedAsset(
    string AbsolutePath,
    string ManagedRelpath);

/// <summary>EXISTING_ASSET 与 I2V 共用的 C006B1 frozen-image verifier。</summary>
public static class ProductionTrustedAssetVerifier
{
    public static async Task<ProductionVerifiedTrustedAsset> VerifyAsync(
        ProductionTrustedAssetSnapshotRecord asset,
        string trustedInputRoot,
        CancellationToken cancellationToken)
    {
        ValidateContract(asset);
        cancellationToken.ThrowIfCancellationRequested();
        var inputRoot = Path.GetFullPath(trustedInputRoot);
        ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, inputRoot);
        var sourcePath = ProductionLocalEnvironment.ResolveUnderRoot(
            inputRoot,
            asset.ManagedRelpath,
            requireExistingFile: true);
        ProductionLocalEnvironment.AssertNoLinkEscape(inputRoot, sourcePath);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(sourcePath))
        {
            throw new InvalidDataException("TRUSTED_ASSET_FILE_INVALID");
        }
        if (new FileInfo(sourcePath).Length != asset.SizeBytes)
        {
            throw new InvalidDataException("TRUSTED_ASSET_SIZE_MISMATCH");
        }
        var digest = await ProductionLocalEnvironment.Sha256FileAsync(sourcePath, cancellationToken)
            .ConfigureAwait(false);
        if (!string.Equals(digest, asset.Sha256, StringComparison.Ordinal))
        {
            throw new InvalidDataException("TRUSTED_ASSET_SHA256_MISMATCH");
        }
        VerifyImageFacts(sourcePath, asset);
        return new ProductionVerifiedTrustedAsset(
            sourcePath,
            Path.GetRelativePath(inputRoot, sourcePath).Replace('\\', '/'));
    }

    private static void ValidateContract(ProductionTrustedAssetSnapshotRecord asset)
    {
        var extension = asset.MediaType switch
        {
            "image/png" => "png",
            "image/jpeg" => "jpg",
            _ => throw new InvalidDataException("TRUSTED_ASSET_MEDIA_TYPE_INVALID"),
        };
        if (!Guid.TryParse(asset.AssetId, out _)
            || !string.Equals(asset.ScopeKind, "autonomous_goal", StringComparison.Ordinal)
            || string.IsNullOrWhiteSpace(asset.ScopeId)
            || !string.Equals(asset.ManagedRootId, "windows.comfy-input.v1", StringComparison.Ordinal)
            || asset.SizeBytes <= 0
            || asset.Width <= 0
            || asset.Height <= 0
            || asset.Sha256.Length != 64)
        {
            throw new InvalidDataException("TRUSTED_ASSET_CONTRACT_INVALID");
        }
        try
        {
            _ = Convert.FromHexString(asset.Sha256);
        }
        catch (FormatException exception)
        {
            throw new InvalidDataException("TRUSTED_ASSET_SHA256_INVALID", exception);
        }
        var expected = $"PicotooPet/assets/v1/{asset.Sha256[..2]}/{asset.Sha256}.{extension}";
        if (!string.Equals(
            asset.ManagedRelpath.Replace('\\', '/'),
            expected,
            StringComparison.Ordinal))
        {
            throw new InvalidDataException("TRUSTED_ASSET_MANAGED_RELPATH_INVALID");
        }
    }

    private static void VerifyImageFacts(
        string sourcePath,
        ProductionTrustedAssetSnapshotRecord asset)
    {
        using var stream = new FileStream(sourcePath, FileMode.Open, FileAccess.Read, FileShare.Read);
        Span<byte> header = stackalloc byte[8];
        if (stream.Read(header) != header.Length)
        {
            throw new InvalidDataException("TRUSTED_ASSET_DECODE_FAILED");
        }
        var isPng = header.SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        var isJpeg = header[0] == 0xff && header[1] == 0xd8 && header[2] == 0xff;
        var decodedMediaType = isPng ? "image/png" : isJpeg ? "image/jpeg" : null;
        if (!string.Equals(decodedMediaType, asset.MediaType, StringComparison.Ordinal))
        {
            throw new InvalidDataException("TRUSTED_ASSET_MIME_MISMATCH");
        }
        stream.Position = 0;
        BitmapDecoder decoder;
        try
        {
            decoder = BitmapDecoder.Create(
                stream,
                BitmapCreateOptions.PreservePixelFormat,
                BitmapCacheOption.OnLoad);
        }
        catch (Exception exception) when (exception is NotSupportedException or FileFormatException)
        {
            throw new InvalidDataException("TRUSTED_ASSET_DECODE_FAILED", exception);
        }
        var frame = decoder.Frames.FirstOrDefault()
            ?? throw new InvalidDataException("TRUSTED_ASSET_DECODE_FAILED");
        if (frame.PixelWidth != asset.Width || frame.PixelHeight != asset.Height)
        {
            throw new InvalidDataException("TRUSTED_ASSET_DIMENSION_MISMATCH");
        }
    }
}

/// <summary>为新 frozen snapshot 与旧 relative-ref plan 提供唯一 I2V 输入解析入口。</summary>
public static class ProductionTrustedInputResolver
{
    public static async Task<string> ResolveAsync(
        ProductionTaskPlanRecord task,
        string trustedInputRoot,
        CancellationToken cancellationToken)
    {
        if (task.TrustedAsset is not null)
        {
            if (task.TrustedInputAssetRef is not null)
            {
                throw new InvalidDataException("COMFY_I2V_INPUT_AUTHORITY_AMBIGUOUS");
            }
            var verified = await ProductionTrustedAssetVerifier.VerifyAsync(
                task.TrustedAsset,
                trustedInputRoot,
                cancellationToken).ConfigureAwait(false);
            return verified.ManagedRelpath;
        }
        if (string.IsNullOrWhiteSpace(task.TrustedInputAssetRef))
        {
            throw new InvalidDataException("COMFY_I2V_INPUT_MISSING");
        }
        // Restart-only compatibility. Remove only when no nonterminal persisted I2V plan
        // remains with trusted_asset null and trusted_input_asset_ref populated.
        var root = Path.GetFullPath(trustedInputRoot);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
        var path = ProductionLocalEnvironment.ResolveUnderRoot(
            root,
            task.TrustedInputAssetRef,
            requireExistingFile: true);
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path))
        {
            throw new InvalidDataException("COMFY_I2V_INPUT_INVALID");
        }
        return Path.GetRelativePath(root, path).Replace('\\', '/');
    }
}
