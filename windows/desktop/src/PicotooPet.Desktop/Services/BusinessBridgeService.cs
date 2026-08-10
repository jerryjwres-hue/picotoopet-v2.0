using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>固定 Inbox/Outbox 业务桥；只搬运严格 Work Package，不执行生产者内容。</summary>
public sealed class BusinessBridgeService
{
    private const long MaxCompressedBytes = 256L * 1024 * 1024;
    private const long MaxUncompressedBytes = 512L * 1024 * 1024;
    private const long MaxSingleInputBytes = 256L * 1024 * 1024;
    private static readonly HashSet<string> AllowedProfiles = new(StringComparer.Ordinal)
    {
        "reviews.voice_of_customer.v1",
        "ideas.pattern_analysis.v1",
    };
    private static readonly HashSet<string> AllowedMediaTypes = new(StringComparer.Ordinal)
    {
        "application/json",
        "application/jsonl",
        "application/x-ndjson",
        "text/csv",
        "text/plain",
    };
    private static readonly HashSet<string> ForbiddenExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".app", ".bat", ".cmd", ".com", ".dll", ".dmg", ".exe", ".js", ".msi", ".ps1", ".py", ".sh",
    };
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly ControlCenterSession _session;

    public BusinessBridgeService(ControlCenterSession session, string? localAppDataRoot = null)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
        var localRoot = localAppDataRoot
            ?? Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        Root = Path.Combine(localRoot, "PicotooPet", "BusinessBridge");
        Inbox = Path.Combine(Root, "Inbox");
        Outbox = Path.Combine(Root, "Outbox");
        Quarantine = Path.Combine(Root, "Quarantine");
        Submitted = Path.Combine(Root, "Submitted");
        Directory.CreateDirectory(Inbox);
        Directory.CreateDirectory(Outbox);
        Directory.CreateDirectory(Quarantine);
        Directory.CreateDirectory(Submitted);
    }

    public string Root { get; }
    public string Inbox { get; }
    public string Outbox { get; }
    public string Quarantine { get; }
    public string Submitted { get; }

    /// <summary>扫描已原子落盘的 ZIP；网络故障保留 Inbox，合同拒绝才隔离。</summary>
    public async Task<BusinessBridgeRunResult> ProcessInboxAsync(CancellationToken cancellationToken)
    {
        var submitted = 0;
        var quarantined = 0;
        var deferred = 0;
        foreach (var packagePath in Directory.EnumerateFiles(Inbox, "*.zip", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var local = ValidateLocalPackage(packagePath);
                await UploadAsync(local, cancellationToken).ConfigureAwait(false);
                MoveSubmitted(local, packagePath);
                submitted++;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (BusinessBridgePackageException exception)
            {
                QuarantineFile(packagePath, exception.Code);
                quarantined++;
            }
            catch (ApiException exception) when (!exception.Retryable)
            {
                QuarantineFile(packagePath, "core_rejected");
                quarantined++;
            }
            catch (IOException)
            {
                deferred++;
            }
            catch (ApiException)
            {
                deferred++;
            }
            catch (HttpRequestException)
            {
                deferred++;
            }
        }
        return new BusinessBridgeRunResult(submitted, quarantined, deferred);
    }

    /// <summary>把已完成 Result Package 幂等送入固定 Outbox。</summary>
    public async Task<int> DeliverCompletedResultsAsync(CancellationToken cancellationToken)
    {
        var delivered = 0;
        var packages = await _session.GetBusinessWorkPackagesAsync(cancellationToken).ConfigureAwait(false);
        foreach (var package in packages.Where(item => item.Status == "Completed" && item.ResultPackageId is not null))
        {
            cancellationToken.ThrowIfCancellationRequested();
            var directory = Path.Combine(Outbox, package.WorkPackageId);
            Directory.CreateDirectory(directory);
            var destination = Path.Combine(directory, "result-package.zip");
            var payload = await _session.DownloadBusinessResultAsync(package.WorkPackageId, cancellationToken)
                .ConfigureAwait(false);
            if (WriteImmutable(destination, payload))
            {
                delivered++;
            }
        }
        return delivered;
    }

    /// <summary>人工动作才导出脱敏 Deep-AI Handoff；不会调用任何付费服务。</summary>
    public async Task<string> ExportDeepAiHandoffAsync(
        string workPackageId,
        CancellationToken cancellationToken)
    {
        var handoff = await _session.GetBusinessDeepAiHandoffAsync(workPackageId, cancellationToken)
            .ConfigureAwait(false)
            ?? throw new InvalidOperationException("所选业务包没有可导出的 Deep-AI Handoff。");
        if (handoff.Status != "ManualReady")
        {
            throw new InvalidOperationException("Deep-AI Handoff 尚未进入 ManualReady。");
        }
        var directory = Path.Combine(Outbox, workPackageId);
        Directory.CreateDirectory(directory);
        var destination = Path.Combine(directory, "deep-ai-handoff.zip");
        var payload = await _session.DownloadBusinessDeepAiHandoffAsync(workPackageId, cancellationToken)
            .ConfigureAwait(false);
        WriteImmutable(destination, payload);
        return destination;
    }

    private async Task UploadAsync(LocalBusinessPackage package, CancellationToken cancellationToken)
    {
        var prepared = await _session.PrepareBusinessUploadAsync(
            new BusinessUploadPrepareRequest(package.Manifest, package.SourceDigest, package.SizeBytes),
            cancellationToken).ConfigureAwait(false);
        var session = prepared.UploadSession;
        if (!string.Equals(session.SourceDigest, package.SourceDigest, StringComparison.Ordinal)
            || session.TotalSizeBytes != package.SizeBytes)
        {
            throw new BusinessBridgePackageException("upload_identity_conflict");
        }
        if (session.Status == "Finalized")
        {
            return;
        }

        await using var stream = new FileStream(
            package.Path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 1024 * 1024,
            useAsync: true);
        if (session.VerifiedSizeBytes < 0 || session.VerifiedSizeBytes > stream.Length)
        {
            throw new BusinessBridgePackageException("resume_offset_invalid");
        }
        stream.Position = session.VerifiedSizeBytes;
        var offset = session.VerifiedSizeBytes;
        var buffer = new byte[MacCoreBusinessAutomationClient.UploadChunkBytes];
        while (offset < stream.Length)
        {
            var wanted = (int)Math.Min(buffer.Length, stream.Length - offset);
            var readTotal = 0;
            while (readTotal < wanted)
            {
                var read = await stream.ReadAsync(
                    buffer.AsMemory(readTotal, wanted - readTotal),
                    cancellationToken).ConfigureAwait(false);
                if (read == 0)
                {
                    throw new EndOfStreamException("Work Package 在上传期间被截断。");
                }
                readTotal += read;
            }
            var chunk = buffer.AsMemory(0, readTotal);
            var digest = Convert.ToHexString(SHA256.HashData(chunk.Span)).ToLowerInvariant();
            session = await _session.UploadBusinessChunkAsync(
                session.UploadSessionId,
                offset,
                digest,
                chunk,
                cancellationToken).ConfigureAwait(false);
            offset += readTotal;
            if (session.VerifiedSizeBytes != offset)
            {
                throw new BusinessBridgePackageException("server_resume_offset_mismatch");
            }
        }
        _ = await _session.FinalizeBusinessUploadAsync(session.UploadSessionId, cancellationToken)
            .ConfigureAwait(false);
    }

    private static LocalBusinessPackage ValidateLocalPackage(string path)
    {
        var file = new FileInfo(path);
        if (!file.Exists || file.Length < 1 || file.Length > MaxCompressedBytes)
        {
            throw new BusinessBridgePackageException("archive_size_invalid");
        }
        var sourceDigest = HashFile(path);
        using var archive = ZipFile.OpenRead(path);
        if (archive.Entries.Count == 0)
        {
            throw new BusinessBridgePackageException("archive_empty");
        }
        var normalized = new Dictionary<string, ZipArchiveEntry>(StringComparer.Ordinal);
        string? root = null;
        long uncompressed = 0;
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName;
            if (name.Contains('\\'))
            {
                throw new BusinessBridgePackageException("unsafe_path");
            }
            var parts = name.Split('/', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 0 || name.StartsWith("/", StringComparison.Ordinal)
                || parts.Any(part => part is "." or ".."))
            {
                throw new BusinessBridgePackageException("unsafe_path");
            }
            root ??= parts[0];
            if (!string.Equals(root, parts[0], StringComparison.Ordinal))
            {
                throw new BusinessBridgePackageException("multiple_roots");
            }
            var key = string.Join('/', parts);
            if (!normalized.TryAdd(key, entry))
            {
                throw new BusinessBridgePackageException("duplicate_path");
            }

            // ZIP Unix high-word attributes are optional. If present, accept only regular files/directories
            // and reject execute bits so producer archives cannot smuggle runnable/link payloads.
            var unixMode = (entry.ExternalAttributes >> 16) & 0xFFFF;
            var fileType = unixMode & 0xF000;
            if ((fileType != 0 && fileType != 0x8000 && fileType != 0x4000)
                || (unixMode & 0x49) != 0)
            {
                throw new BusinessBridgePackageException("special_or_executable_payload");
            }

            uncompressed = checked(uncompressed + entry.Length);
            if (entry.Length > MaxSingleInputBytes || uncompressed > MaxUncompressedBytes)
            {
                throw new BusinessBridgePackageException("uncompressed_size_invalid");
            }
            if (!name.EndsWith("/", StringComparison.Ordinal)
                && ForbiddenExtensions.Contains(Path.GetExtension(name)))
            {
                throw new BusinessBridgePackageException("executable_payload");
            }
        }

        var manifestKey = $"{root}/work-package.json";
        if (!normalized.TryGetValue(manifestKey, out var manifestEntry))
        {
            throw new BusinessBridgePackageException("manifest_missing");
        }
        BusinessWorkPackageManifest manifest;
        using (var manifestStream = manifestEntry.Open())
        {
            manifest = JsonSerializer.Deserialize<BusinessWorkPackageManifest>(manifestStream, JsonOptions)
                ?? throw new BusinessBridgePackageException("manifest_invalid");
        }
        ValidateManifest(manifest);
        var declared = new HashSet<string>(StringComparer.Ordinal) { manifestKey };
        foreach (var descriptor in manifest.Inputs)
        {
            var key = $"{root}/{descriptor.Path}";
            declared.Add(key);
            if (!normalized.TryGetValue(key, out var entry)
                || entry.FullName.EndsWith("/", StringComparison.Ordinal))
            {
                throw new BusinessBridgePackageException("declared_input_missing");
            }
            if (entry.Length != descriptor.SizeBytes)
            {
                throw new BusinessBridgePackageException("input_size_mismatch");
            }
            using var input = entry.Open();
            var digest = Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
            if (!string.Equals(digest, descriptor.Sha256, StringComparison.Ordinal))
            {
                throw new BusinessBridgePackageException("input_hash_mismatch");
            }
        }
        var actualFiles = normalized
            .Where(pair => !pair.Value.FullName.EndsWith("/", StringComparison.Ordinal))
            .Select(pair => pair.Key)
            .ToHashSet(StringComparer.Ordinal);
        if (!actualFiles.SetEquals(declared))
        {
            throw new BusinessBridgePackageException("undeclared_file");
        }
        return new LocalBusinessPackage(path, manifest, sourceDigest, file.Length);
    }

    private static void ValidateManifest(BusinessWorkPackageManifest manifest)
    {
        if (manifest.SchemaVersion != "1.0" || !Guid.TryParse(manifest.PackageId, out _))
        {
            throw new BusinessBridgePackageException("manifest_identity_invalid");
        }
        if (manifest.Inputs.Length is < 1 or > 64 || !AllowedProfiles.Contains(manifest.AnalysisProfile))
        {
            throw new BusinessBridgePackageException("manifest_profile_invalid");
        }
        var artifactIds = new HashSet<string>(StringComparer.Ordinal);
        var inputPaths = new HashSet<string>(StringComparer.Ordinal);
        foreach (var input in manifest.Inputs)
        {
            if (!artifactIds.Add(input.ArtifactId)
                || !inputPaths.Add(input.Path)
                || !AllowedMediaTypes.Contains(input.MediaType)
                || input.SizeBytes < 0
                || input.SizeBytes > MaxSingleInputBytes
                || input.Path.Contains('\\')
                || input.Path.StartsWith("/", StringComparison.Ordinal)
                || !input.Path.StartsWith("inputs/", StringComparison.Ordinal)
                || input.Path.Split('/').Any(part => part is "." or ".." or "")
                || ForbiddenExtensions.Contains(Path.GetExtension(input.Path)))
            {
                throw new BusinessBridgePackageException("manifest_input_invalid");
            }
        }
    }

    private void MoveSubmitted(LocalBusinessPackage package, string source)
    {
        var destination = Path.Combine(Submitted, $"{package.Manifest.PackageId}.zip");
        if (File.Exists(destination))
        {
            if (string.Equals(HashFile(destination), package.SourceDigest, StringComparison.Ordinal))
            {
                File.Delete(source);
                return;
            }
            throw new BusinessBridgePackageException("submitted_identity_conflict");
        }
        File.Move(source, destination);
    }

    private void QuarantineFile(string source, string reason)
    {
        if (!File.Exists(source))
        {
            return;
        }
        var identity = Guid.NewGuid().ToString("N");
        var destination = Path.Combine(Quarantine, $"{identity}.zip");
        File.Move(source, destination);
        File.WriteAllText(Path.Combine(Quarantine, $"{identity}.reason.txt"), reason);
    }

    private static bool WriteImmutable(string destination, ReadOnlySpan<byte> payload)
    {
        var temporary = destination + ".partial-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllBytes(temporary, payload.ToArray());
            if (File.Exists(destination))
            {
                var existing = HashFile(destination);
                var candidate = HashFile(temporary);
                if (!string.Equals(existing, candidate, StringComparison.Ordinal))
                {
                    throw new IOException("Outbox immutable result conflict.");
                }
                File.Delete(temporary);
                return false;
            }
            File.Move(temporary, destination);
            return true;
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private sealed record LocalBusinessPackage(
        string Path,
        BusinessWorkPackageManifest Manifest,
        string SourceDigest,
        long SizeBytes);
}

/// <summary>一次 Inbox 扫描的安全计数，不含用户数据。</summary>
public sealed record BusinessBridgeRunResult(int Submitted, int Quarantined, int Deferred);

/// <summary>本地包合同失败；Code 可写入安全诊断但不包含用户正文。</summary>
public sealed class BusinessBridgePackageException : InvalidOperationException
{
    public BusinessBridgePackageException(string code) : base(code) => Code = code;

    public string Code { get; }
}
