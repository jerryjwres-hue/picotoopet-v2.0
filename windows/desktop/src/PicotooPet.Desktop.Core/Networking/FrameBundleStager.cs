using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>Windows 原生 ZIP 暂存；只交付哈希校验过的数据，不创建任务或 GPU 权限。</summary>
public static class FrameBundleStager
{
    private const long MaxObjectBytes     = 64L * 1024 * 1024;
    private const long MaxTotalBytes      = 128L * 1024 * 1024;
    private const int MaxManifestBytes    = 128 * 1024;
    private static readonly Regex Sha     = new("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);
    private static readonly Regex AssetId = new("^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$", RegexOptions.CultureInvariant);
    private static readonly Regex ShotId  = new("^[A-Za-z0-9_-]{1,80}$", RegexOptions.CultureInvariant);

    /// <summary>预期哈希必须来自 Mac 可信审批/冻结 Plan，不能从收到的 ZIP 自选。</summary>
    public static async Task<FrameStagingReceipt> StageAsync(
        string zipPath,
        string expectedManifestSha256,
        string workerRoot,
        CancellationToken cancellationToken = default)
    {
        if (!Sha.IsMatch(expectedManifestSha256))
        {
            throw new InvalidDataException("FRAME_STAGE_EXPECTED_SHA_INVALID");
        }

        // 整个 ZIP 只允许已知的受控文件名；不接受任意归档路径或压缩炸弹。
        using var archive = ZipFile.OpenRead(zipPath);
        var files = archive.Entries;
        if (files.Count is < 2 or > 66 ||
            files.Any(entry => entry.FullName.EndsWith('/') ||
                entry.Length > MaxObjectBytes ||
                entry.CompressedLength > MaxObjectBytes + 1024 ||
                ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000) ||
            files.Select(entry => entry.FullName).Distinct(StringComparer.Ordinal).Count() != files.Count)
        {
            throw new InvalidDataException("FRAME_STAGE_ZIP_ENTRIES_INVALID");
        }

        var metadata = archive.GetEntry("manifest.json")
            ?? throw new InvalidDataException("FRAME_STAGE_MANIFEST_MISSING");
        if (metadata.Length > MaxManifestBytes)
        {
            throw new InvalidDataException("FRAME_STAGE_MANIFEST_TOO_LARGE");
        }

        byte[] canonical;
        await using (var stream = metadata.Open())
        {
            using var buffer = new MemoryStream();
            await stream.CopyToAsync(buffer, cancellationToken).ConfigureAwait(false);
            canonical = buffer.ToArray();
        }
        if (!EqualsSha(canonical, expectedManifestSha256))
        {
            throw new InvalidDataException("FRAME_STAGE_MANIFEST_SHA_MISMATCH");
        }

        using var document = JsonDocument.Parse(canonical);
        var root = document.RootElement;
        if (!ExactKeys(root, "contract", "storypack_sha256", "owner_subject_sha256", "bindings") ||
            root.GetProperty("contract").GetString() != "picotoo.frame-source-manifest.v1" ||
            !ValidSha(root.GetProperty("storypack_sha256")) ||
            !ValidSha(root.GetProperty("owner_subject_sha256")))
        {
            throw new InvalidDataException("FRAME_STAGE_MANIFEST_CONTRACT_INVALID");
        }

        var inputBindings = root.GetProperty("bindings");
        if (inputBindings.ValueKind != JsonValueKind.Array ||
            inputBindings.GetArrayLength() is < 1 or > 960)
        {
            throw new InvalidDataException("FRAME_STAGE_BINDINGS_INVALID");
        }

        var declared = new HashSet<(string Shot, string Role, string Reference)>();
        var bindings = new List<(string Shot, string Role, string Reference, string Sha)>();
        foreach (var binding in inputBindings.EnumerateArray())
        {
            if (!ExactKeys(binding, "shot_id", "role", "asset_ref", "managed_sha256"))
            {
                throw new InvalidDataException("FRAME_STAGE_BINDING_CONTRACT_INVALID");
            }

            var shot  = binding.GetProperty("shot_id").GetString() ?? "";
            var role  = binding.GetProperty("role").GetString() ?? "";
            var asset = binding.GetProperty("asset_ref").GetString() ?? "";
            var hash  = binding.GetProperty("managed_sha256").GetString() ?? "";
            if (!ShotId.IsMatch(shot) || (role != "first" && role != "last") ||
                !AssetId.IsMatch(asset) || !Sha.IsMatch(hash) ||
                !declared.Add((shot, role, asset)))
            {
                throw new InvalidDataException("FRAME_STAGE_BINDING_INVALID");
            }
            bindings.Add((shot, role, asset, hash));
        }

        var digests = bindings.Select(row => row.Sha)
            .Distinct(StringComparer.Ordinal).OrderBy(x => x, StringComparer.Ordinal).ToArray();
        var permitted = new HashSet<string>(digests.Select(x => $"objects/{x}"), StringComparer.Ordinal)
        {
            "manifest.json",
        };
        if (digests.Length > 64 || files.Any(entry => !permitted.Contains(entry.FullName)) ||
            files.Count != permitted.Count ||
            digests.Sum(hash => archive.GetEntry($"objects/{hash}")?.Length ?? MaxTotalBytes + 1)
                > MaxTotalBytes)
        {
            throw new InvalidDataException("FRAME_STAGE_UNEXPECTED_OBJECT_SET");
        }

        // 不能在未知的重解析点或项目外路径存储任何私有素材。
        var project = Path.GetFullPath(workerRoot);
        if (!Directory.Exists(project) || IsLink(project))
        {
            throw new InvalidDataException("FRAME_STAGE_WORKER_ROOT_INVALID");
        }
        var target = project;
        foreach (var segment in new[] { "_queue", "executor_bridge", "staged_references" })
        {
            target = Path.Combine(target, segment);
            if (IsLink(target))
            {
                throw new InvalidDataException("FRAME_STAGE_REPARSE_POINT_FORBIDDEN");
            }
            Directory.CreateDirectory(target);
            if (IsLink(target))
            {
                throw new InvalidDataException("FRAME_STAGE_REPARSE_POINT_FORBIDDEN");
            }
        }

        var refs = new Dictionary<string, string>(StringComparer.Ordinal);
        long verifiedBytes = 0;
        foreach (var hash in digests)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var entry = archive.GetEntry($"objects/{hash}")
                ?? throw new InvalidDataException("FRAME_STAGE_OBJECT_MISSING");
            if (entry.Length > MaxObjectBytes)
            {
                throw new InvalidDataException("FRAME_STAGE_OBJECT_TOO_LARGE");
            }

            var temp = Path.Combine(target, $".frame-{Guid.NewGuid():N}.tmp");
            try
            {
                // 写入临时文件，流式哈希确认字节，再原子发布为只由 SHA 派生的名称。
                using var sha256 = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                byte[] first = new byte[16];
                var prefixLength = 0;
                long count = 0;
                await using (var source = entry.Open())
                await using (var output = new FileStream(
                    temp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 1024,
                    FileOptions.Asynchronous))
                {
                    var buffer = new byte[1024 * 1024];
                    int length;
                    while ((length = await source.ReadAsync(buffer, cancellationToken)
                        .ConfigureAwait(false)) > 0)
                    {
                        count += length;
                        if (count > MaxObjectBytes || count > entry.Length)
                        {
                            throw new InvalidDataException("FRAME_STAGE_OBJECT_SIZE_CHANGED");
                        }
                        var toCopy = Math.Min(length, first.Length - prefixLength);
                        if (toCopy > 0)
                        {
                            Array.Copy(buffer, 0, first, prefixLength, toCopy);
                            prefixLength += toCopy;
                        }
                        sha256.AppendData(buffer, 0, length);
                        await output.WriteAsync(buffer.AsMemory(0, length), cancellationToken)
                            .ConfigureAwait(false);
                    }
                    await output.FlushAsync(cancellationToken).ConfigureAwait(false);
                }
                if (count != entry.Length ||
                    !string.Equals(Convert.ToHexString(sha256.GetHashAndReset()), hash,
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException("FRAME_STAGE_OBJECT_SHA_MISMATCH");
                }

                var ext = ImageExtension(first, prefixLength);
                var name = $"{hash}{ext}";
                var finalPath = Path.Combine(target, name);
                if (!File.Exists(finalPath) && !IsLink(finalPath))
                {
                    try
                    {
                        // 不能 overwrite：并发旧文件只有通过重新哈希才能复用。
                        File.Move(temp, finalPath, overwrite: false);
                    }
                    catch (IOException) when (File.Exists(finalPath))
                    {
                        // 目标由另一导入者创建；在下方进行独立校验。
                    }
                }
                if (!File.Exists(finalPath) || IsLink(finalPath) ||
                    !await VerifyFileAsync(finalPath, hash, cancellationToken).ConfigureAwait(false))
                {
                    throw new InvalidDataException("FRAME_STAGE_DESTINATION_SHA_MISMATCH");
                }
                verifiedBytes += count;
                refs.Add(hash, $"../_queue/executor_bridge/staged_references/{name}");
            }
            finally
            {
                File.Delete(temp);
            }
        }

        return new FrameStagingReceipt(
            expectedManifestSha256,
            root.GetProperty("storypack_sha256").GetString()!,
            root.GetProperty("owner_subject_sha256").GetString()!,
            verifiedBytes,
            refs,
            bindings.Select(item => new FrameStagingBinding(
                item.Shot, item.Role, item.Reference, item.Sha, refs[item.Sha])).ToArray(),
            WorkerLocalBytesVerified: true,
            CanQueue: false,
            GpuAuthorized: false);
    }

    private static bool ExactKeys(JsonElement element, params string[] allowed)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            return false;
        }
        var properties = element.EnumerateObject().Select(property => property.Name).ToArray();
        return properties.Length == allowed.Length &&
            properties.Distinct(StringComparer.Ordinal).Count() == allowed.Length &&
            properties.All(name => allowed.Contains(name, StringComparer.Ordinal));
    }

    private static bool ValidSha(JsonElement value) =>
        value.ValueKind == JsonValueKind.String && Sha.IsMatch(value.GetString() ?? "");

    private static bool EqualsSha(byte[] bytes, string expected) =>
        string.Equals(Convert.ToHexString(SHA256.HashData(bytes)), expected,
            StringComparison.OrdinalIgnoreCase);

    private static bool IsLink(string path) =>
        (File.Exists(path) || Directory.Exists(path)) &&
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;

    private static string ImageExtension(byte[] start, int length)
    {
        if (length >= 8 && start.AsSpan(0, 8).SequenceEqual(
            new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }))
        {
            return ".png";
        }
        if (length >= 3 && start[0] == 255 && start[1] == 216 && start[2] == 255)
        {
            return ".jpg";
        }
        if (length >= 12 && Encoding.ASCII.GetString(start, 0, 4) == "RIFF" &&
            Encoding.ASCII.GetString(start, 8, 4) == "WEBP")
        {
            return ".webp";
        }
        throw new InvalidDataException("FRAME_STAGE_NOT_AN_IMAGE");
    }

    private static async Task<bool> VerifyFileAsync(
        string filename, string expectedSha, CancellationToken cancellationToken)
    {
        await using var input = new FileStream(
            filename, FileMode.Open, FileAccess.Read, FileShare.Read,
            1024 * 1024, FileOptions.Asynchronous);
        if (input.Length > MaxObjectBytes)
        {
            return false;
        }
        var hash = await SHA256.HashDataAsync(input, cancellationToken).ConfigureAwait(false);
        return string.Equals(Convert.ToHexString(hash), expectedSha,
            StringComparison.OrdinalIgnoreCase);
    }
}

/// <summary>单个镜头参考图在 Windows 本地验证过的只读路径映射。</summary>
public sealed record FrameStagingBinding(
    string ShotId, string Role, string AssetRef, string ManagedSha256, string WorkerRef);

/// <summary>仅证明数据完整性；不得用于解除 GPU HOLD 或向生产队列写入。</summary>
public sealed record FrameStagingReceipt(
    string SourceBindingsSha256,
    string StorypackSha256,
    string OwnerSubjectSha256,
    long VerifiedBytes,
    IReadOnlyDictionary<string, string> WorkerRefPathsByDigest,
    IReadOnlyList<FrameStagingBinding> Bindings,
    bool WorkerLocalBytesVerified,
    bool CanQueue,
    bool GpuAuthorized,
    string? CoreStagingStatus = null);
