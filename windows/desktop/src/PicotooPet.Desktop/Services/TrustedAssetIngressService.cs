using System.Security.Cryptography;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>受信资产导入失败；Message 永远是封闭错误码，不含路径或字节内容。</summary>
public sealed class TrustedAssetIngressException : Exception
{
    public TrustedAssetIngressException(string code, Exception? innerException = null)
        : base(code, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}

/// <summary>一次导入结果：Core 记录、是否复用已存在的本地对象。</summary>
public sealed record TrustedAssetImportResult(TrustedAssetRecord Record, bool LocalObjectReused);

/// <summary>
/// C006B1 Windows 字节入口：用户选择的源路径只存在于本进程；字节只复制到 ComfyUI input 根下的
/// PicotooPet 内容寻址目录；Core 只收到有界事实。不是 Production 任务，也不集成 EXISTING_ASSET。
/// </summary>
public sealed class TrustedAssetIngressService
{
    private const string StagingDirectoryName = ".staging";
    private static readonly byte[] PngSignature = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

    private readonly string _inputRoot;
    private readonly ITrustedAssetRegistrar _registrar;

    /// <summary>inputRoot 必须是组合根解析出的 ComfyUI input 目录；registrar 负责 Core 登记。</summary>
    public TrustedAssetIngressService(string inputRoot, ITrustedAssetRegistrar registrar)
    {
        if (string.IsNullOrWhiteSpace(inputRoot))
        {
            throw new ArgumentException("TRUSTED_ASSET_ROOT_INVALID", nameof(inputRoot));
        }
        _inputRoot = Path.GetFullPath(inputRoot);
        _registrar = registrar ?? throw new ArgumentNullException(nameof(registrar));
    }

    /// <summary>导入一张本地 PNG/JPEG；返回 Core 签发的资产记录。</summary>
    public async Task<TrustedAssetImportResult> ImportImageAsync(
        string scopeKind,
        string scopeId,
        string sourcePath,
        CancellationToken cancellationToken)
    {
        ValidateScope(scopeKind, scopeId);
        ValidateRoot();
        var source = ValidateSource(sourcePath);

        EnsureManagedDirectory($"{TrustedAssetConstants.RelativeRoot}/{StagingDirectoryName}");
        var partialPath = ProductionLocalEnvironment.ResolveUnderRoot(
            _inputRoot,
            $"{TrustedAssetConstants.RelativeRoot}/{StagingDirectoryName}/{Guid.NewGuid():N}.partial",
            requireExistingFile: false);

        try
        {
            await SnapshotAsync(source, partialPath, cancellationToken).ConfigureAwait(false);
            var facts = await VerifyStagedAsync(partialPath, cancellationToken).ConfigureAwait(false);
            var relative = TrustedAssetConstants.DeriveRelativePath(facts.Sha256, facts.MediaType);
            var reused = await InstallAsync(partialPath, relative, facts, cancellationToken).ConfigureAwait(false);

            var request = new TrustedAssetRegisterRequest(
                "1.0",
                scopeKind,
                scopeId,
                // 稳定幂等键：网络歧义后重试得到同一 Core 资产。
                $"win-import.v1:{scopeKind}:{scopeId}:{facts.Sha256}",
                facts.Sha256,
                facts.SizeBytes,
                facts.MediaType,
                facts.Width,
                facts.Height,
                null,
                TrustedAssetConstants.ManagedRootId,
                TrustedAssetConstants.SourceKind);
            var record = await RegisterAsync(request, cancellationToken).ConfigureAwait(false);
            if (!MatchesRequest(record, request, relative))
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_CORE_MISMATCH");
            }
            return new TrustedAssetImportResult(record, reused);
        }
        finally
        {
            TryDelete(partialPath);
        }
    }

    private async Task<TrustedAssetRecord> RegisterAsync(
        TrustedAssetRegisterRequest request,
        CancellationToken cancellationToken)
    {
        try
        {
            return await _registrar.RegisterAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception) when (exception is not TrustedAssetIngressException)
        {
            // 本地内容寻址对象保留（无害）；重试复用同一对象和同一幂等键。
            throw new TrustedAssetIngressException("TRUSTED_ASSET_REGISTRATION_FAILED", exception);
        }
    }

    private static void ValidateScope(string scopeKind, string scopeId)
    {
        if (scopeKind is not (TrustedAssetConstants.ScopeAutonomousGoal or TrustedAssetConstants.ScopeProject)
            || string.IsNullOrWhiteSpace(scopeId)
            || scopeId.Length > 120
            || !scopeId.All(static ch => char.IsAsciiLetterOrDigit(ch) || ch is '_' or '.' or '-'))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SCOPE_INVALID");
        }
    }

    private void ValidateRoot()
    {
        try
        {
            if (!Directory.Exists(_inputRoot))
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_ROOT_INVALID");
            }
            ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, _inputRoot);
        }
        catch (InvalidDataException exception)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_ROOT_INVALID", exception);
        }
    }

    private static string ValidateSource(string sourcePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath) || sourcePath.Length > 1024 || !Path.IsPathRooted(sourcePath))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID");
        }
        var full = Path.GetFullPath(sourcePath);
        if (Directory.Exists(full) || !File.Exists(full))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID");
        }
        if (!ProductionLocalEnvironment.IsOrdinaryFile(full))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_REPARSE_FORBIDDEN");
        }
        return full;
    }

    /// <summary>逐级创建受管目录，并确认每一级都不是重解析点且仍在信任根内。</summary>
    private void EnsureManagedDirectory(string relativeDirectory)
    {
        var relative = string.Empty;
        foreach (var segment in relativeDirectory.Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            relative = relative.Length == 0 ? segment : $"{relative}/{segment}";
            var current = ProductionLocalEnvironment.ResolveUnderRoot(
                _inputRoot,
                relative,
                requireExistingFile: false);
            try
            {
                if (File.Exists(current))
                {
                    throw new TrustedAssetIngressException("TRUSTED_ASSET_LOCAL_CONFLICT");
                }
                Directory.CreateDirectory(current);
                ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, current);
            }
            catch (InvalidDataException exception)
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_ROOT_INVALID", exception);
            }
        }
    }

    private static async Task SnapshotAsync(string source, string partialPath, CancellationToken cancellationToken)
    {
        try
        {
            await using var input = new FileStream(
                source,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                bufferSize: 1024 * 1024,
                options: FileOptions.Asynchronous | FileOptions.SequentialScan);
            if (input.Length is <= 0 or > TrustedAssetConstants.MaxBytes)
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_TOO_LARGE");
            }
            await using var output = new FileStream(
                partialPath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                bufferSize: 1024 * 1024,
                options: FileOptions.Asynchronous | FileOptions.WriteThrough);
            var buffer = new byte[1024 * 1024];
            long total = 0;
            while (true)
            {
                var read = await input.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                if (read == 0)
                {
                    break;
                }
                total += read;
                if (total > TrustedAssetConstants.MaxBytes)
                {
                    throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_TOO_LARGE");
                }
                await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
            }
            await output.FlushAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (IOException exception)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID", exception);
        }
        catch (UnauthorizedAccessException exception)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID", exception);
        }
    }

    private sealed record StagedFacts(string Sha256, long SizeBytes, string MediaType, int Width, int Height);

    /// <summary>在受管暂存快照上重新计算大小/SHA，并从字节解码 MIME 与尺寸（不信任扩展名）。</summary>
    private static async Task<StagedFacts> VerifyStagedAsync(string partialPath, CancellationToken cancellationToken)
    {
        if (!ProductionLocalEnvironment.IsOrdinaryFile(partialPath))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID");
        }
        var size = new FileInfo(partialPath).Length;
        if (size is <= 0 or > TrustedAssetConstants.MaxBytes)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_TOO_LARGE");
        }
        var sha256 = await ProductionLocalEnvironment.Sha256FileAsync(partialPath, cancellationToken)
            .ConfigureAwait(false);
        var bytes = await File.ReadAllBytesAsync(partialPath, cancellationToken).ConfigureAwait(false);
        if (bytes.LongLength != size)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_SOURCE_INVALID");
        }
        var (mediaType, width, height) = DecodeImage(bytes);
        return new StagedFacts(sha256, size, mediaType, width, height);
    }

    /// <summary>仅接受 PNG/JPEG；魔数与解码器类型必须一致，并完整解码以拒绝截断/伪造文件。</summary>
    internal static (string MediaType, int Width, int Height) DecodeImage(byte[] bytes)
    {
        string expected;
        if (bytes.Length > PngSignature.Length && bytes.AsSpan(0, PngSignature.Length).SequenceEqual(PngSignature))
        {
            expected = TrustedAssetConstants.MediaTypePng;
        }
        else if (bytes.Length > 3 && bytes[0] == 0xFF && bytes[1] == 0xD8 && bytes[2] == 0xFF)
        {
            expected = TrustedAssetConstants.MediaTypeJpeg;
        }
        else
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_MEDIA_UNSUPPORTED");
        }

        try
        {
            using var stream = new MemoryStream(bytes, writable: false);
            var decoder = BitmapDecoder.Create(
                stream,
                BitmapCreateOptions.PreservePixelFormat | BitmapCreateOptions.IgnoreColorProfile,
                BitmapCacheOption.None);
            var actual = decoder switch
            {
                PngBitmapDecoder => TrustedAssetConstants.MediaTypePng,
                JpegBitmapDecoder => TrustedAssetConstants.MediaTypeJpeg,
                _ => string.Empty,
            };
            if (actual != expected || decoder.Frames.Count < 1)
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_MEDIA_UNSUPPORTED");
            }
            var frame = decoder.Frames[0];
            var width = frame.PixelWidth;
            var height = frame.PixelHeight;
            if (width is < 1 or > TrustedAssetConstants.MaxDimension
                || height is < 1 or > TrustedAssetConstants.MaxDimension
                || (long)width * height > TrustedAssetConstants.MaxPixels)
            {
                throw new TrustedAssetIngressException("TRUSTED_ASSET_MEDIA_UNSUPPORTED");
            }
            // 完整解码一次，截断或损坏的图片在此失败。
            var stride = ((width * frame.Format.BitsPerPixel) + 7) / 8;
            var pixels = new byte[(long)stride * height];
            frame.CopyPixels(pixels, stride, 0);
            return (actual, width, height);
        }
        catch (TrustedAssetIngressException)
        {
            throw;
        }
        catch (Exception exception) when (exception is NotSupportedException
            or InvalidOperationException
            or FileFormatException
            or IOException
            or ArgumentException
            or OverflowException)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_MEDIA_UNSUPPORTED", exception);
        }
    }

    /// <summary>原子安装内容寻址对象；已存在则逐项验证后复用，冲突绝不覆盖。</summary>
    private async Task<bool> InstallAsync(
        string partialPath,
        string relative,
        StagedFacts facts,
        CancellationToken cancellationToken)
    {
        EnsureManagedDirectory(relative[..relative.LastIndexOf('/')]);
        var finalPath = ProductionLocalEnvironment.ResolveUnderRoot(_inputRoot, relative, requireExistingFile: false);
        try
        {
            ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, finalPath);
        }
        catch (InvalidDataException exception)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_LOCAL_CONFLICT", exception);
        }

        if (File.Exists(finalPath) || Directory.Exists(finalPath))
        {
            await VerifyExistingAsync(finalPath, facts, cancellationToken).ConfigureAwait(false);
            return true;
        }
        try
        {
            File.Move(partialPath, finalPath, overwrite: false);
            return false;
        }
        catch (IOException) when (File.Exists(finalPath))
        {
            // 并发写入者先到：同样要求精确匹配才复用。
            await VerifyExistingAsync(finalPath, facts, cancellationToken).ConfigureAwait(false);
            return true;
        }
    }

    private async Task VerifyExistingAsync(string finalPath, StagedFacts facts, CancellationToken cancellationToken)
    {
        try
        {
            ProductionLocalEnvironment.AssertNoLinkEscape(_inputRoot, finalPath);
        }
        catch (InvalidDataException exception)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_LOCAL_CONFLICT", exception);
        }
        if (!ProductionLocalEnvironment.IsOrdinaryFile(finalPath)
            || new FileInfo(finalPath).Length != facts.SizeBytes)
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_LOCAL_CONFLICT");
        }
        var actual = await ProductionLocalEnvironment.Sha256FileAsync(finalPath, cancellationToken)
            .ConfigureAwait(false);
        if (!CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.ASCII.GetBytes(actual),
                System.Text.Encoding.ASCII.GetBytes(facts.Sha256)))
        {
            throw new TrustedAssetIngressException("TRUSTED_ASSET_LOCAL_CONFLICT");
        }
    }

    private static bool MatchesRequest(TrustedAssetRecord record, TrustedAssetRegisterRequest request, string relative) =>
        record.SchemaVersion == "1.0"
        && !string.IsNullOrWhiteSpace(record.AssetId)
        && record.ScopeKind == request.ScopeKind
        && record.ScopeId == request.ScopeId
        && record.Sha256 == request.Sha256
        && record.SizeBytes == request.SizeBytes
        && record.MediaType == request.MediaType
        && record.Width == request.Width
        && record.Height == request.Height
        && record.DurationMs is null
        && record.ManagedRootId == TrustedAssetConstants.ManagedRootId
        && record.ManagedRelPath == relative
        && record.SourceKind == TrustedAssetConstants.SourceKind;

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 暂存文件位于受管 .staging 下，清理失败无害。
        }
        catch (UnauthorizedAccessException)
        {
            // 同上。
        }
    }
}
