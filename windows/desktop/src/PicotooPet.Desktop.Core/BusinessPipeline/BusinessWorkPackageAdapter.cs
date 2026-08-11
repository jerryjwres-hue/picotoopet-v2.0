using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.BusinessPipeline;

/// <summary>把用户明确选择的普通文件转换成严格 Work Package v1；不会执行或解释文件内容。</summary>
public abstract class BusinessWorkPackageAdapter
{
    private const long MaxSingleInputBytes = 256L * 1024 * 1024;
    private const long MaxTotalInputBytes = 512L * 1024 * 1024;
    private const int MaxInputFiles = 64;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
    };
    private static readonly IReadOnlyDictionary<string, string> MediaTypes =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [".csv"] = "text/csv",
            [".json"] = "application/json",
            [".jsonl"] = "application/x-ndjson",
            [".txt"] = "text/plain",
        };

    protected abstract string AdapterProfile { get; }
    protected abstract string AnalysisProfile { get; }
    protected abstract string ProducerId { get; }
    protected virtual string ProducerVersion => "2.3.21.1";

    public BusinessAdapterBuildResult BuildPackage(BusinessAdapterBuildRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        var projectKey = RequireBoundedText(request.ProjectKey, 1, 200, "project_key_invalid");
        var objective = RequireBoundedText(request.Objective, 1, 2000, "objective_invalid");
        if (string.IsNullOrWhiteSpace(request.OutputDirectory))
        {
            throw new BusinessAdapterException("output_directory_invalid");
        }

        var sources = CollectSources(request.SourcePath);
        if (sources.Count is < 1 or > MaxInputFiles)
        {
            throw new BusinessAdapterException("input_count_invalid");
        }

        var descriptors = new List<BusinessInputDescriptor>(sources.Count);
        var sourceFacts = new List<SourceFact>(sources.Count);
        long totalBytes = 0;
        for (var index = 0; index < sources.Count; index++)
        {
            var source = sources[index];
            var extension = Path.GetExtension(source);
            if (!MediaTypes.TryGetValue(extension, out var mediaType))
            {
                throw new BusinessAdapterException("unsupported_extension");
            }
            var info = new FileInfo(source);
            if (!info.Exists || info.Length < 1 || info.Length > MaxSingleInputBytes)
            {
                throw new BusinessAdapterException("input_size_invalid");
            }
            totalBytes = checked(totalBytes + info.Length);
            if (totalBytes > MaxTotalInputBytes)
            {
                throw new BusinessAdapterException("total_input_size_invalid");
            }
            var digest = HashFile(source);
            var safeName = SanitizeFileName(Path.GetFileName(source));
            var archivePath = $"inputs/{index + 1:D3}-{safeName}";
            descriptors.Add(
                new BusinessInputDescriptor(
                    $"input-{index + 1:D3}",
                    archivePath,
                    mediaType,
                    digest,
                    info.Length,
                    RecordKeyField(extension)));
            sourceFacts.Add(new SourceFact(source, archivePath, digest, info.Length));
        }

        var identity = ComputeIdentity(projectKey, objective, sourceFacts);
        var packageId = DeterministicGuid(identity).ToString();
        var manifest = new BusinessWorkPackageManifest(
            "1.0",
            packageId,
            $"{AdapterProfile}:{packageId}",
            ProducerId,
            ProducerVersion,
            DateTimeOffset.UtcNow,
            projectKey,
            AnalysisProfile,
            objective,
            descriptors.ToArray());

        var outputDirectory = Path.GetFullPath(request.OutputDirectory);
        Directory.CreateDirectory(outputDirectory);
        RejectReparsePoint(outputDirectory);
        var destination = Path.Combine(outputDirectory, packageId + ".zip");
        if (!File.Exists(destination))
        {
            WritePackage(destination, manifest, sourceFacts);
        }
        else
        {
            VerifyExistingPackage(destination, manifest, sourceFacts);
        }
        return new BusinessAdapterBuildResult(
            destination,
            manifest,
            HashFile(destination),
            new FileInfo(destination).Length);
    }

    protected virtual string? RecordKeyField(string extension) => null;

    private List<string> CollectSources(string sourcePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            throw new BusinessAdapterException("source_missing");
        }
        var fullPath = Path.GetFullPath(sourcePath);
        if (File.Exists(fullPath))
        {
            RejectReparsePoint(fullPath);
            return [fullPath];
        }
        if (!Directory.Exists(fullPath))
        {
            throw new BusinessAdapterException("source_missing");
        }

        var files = new List<string>();
        var pending = new Stack<string>();
        pending.Push(fullPath);
        while (pending.Count > 0)
        {
            var directory = pending.Pop();
            RejectReparsePoint(directory);
            foreach (var entry in Directory.EnumerateFileSystemEntries(directory)
                         .OrderBy(item => item, StringComparer.OrdinalIgnoreCase))
            {
                RejectReparsePoint(entry);
                var attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.Directory) != 0)
                {
                    pending.Push(entry);
                    continue;
                }
                files.Add(Path.GetFullPath(entry));
                if (files.Count > MaxInputFiles)
                {
                    throw new BusinessAdapterException("input_count_invalid");
                }
            }
        }
        files.Sort(StringComparer.OrdinalIgnoreCase);
        return files;
    }

    private void WritePackage(
        string destination,
        BusinessWorkPackageManifest manifest,
        IReadOnlyList<SourceFact> sources)
    {
        var temporary = destination + ".partial-" + Guid.NewGuid().ToString("N");
        try
        {
            using (var archive = ZipFile.Open(temporary, ZipArchiveMode.Create))
            {
                var root = manifest.PackageId;
                for (var index = 0; index < sources.Count; index++)
                {
                    var source = sources[index];
                    var entry = archive.CreateEntry($"{root}/{source.ArchivePath}", CompressionLevel.Optimal);
                    using var output = entry.Open();
                    using var input = File.OpenRead(source.FullPath);
                    input.CopyTo(output);
                }
                var manifestEntry = archive.CreateEntry($"{root}/work-package.json", CompressionLevel.Optimal);
                using var stream = manifestEntry.Open();
                JsonSerializer.Serialize(stream, manifest, JsonOptions);
            }
            File.Move(temporary, destination);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    private static void VerifyExistingPackage(
        string destination,
        BusinessWorkPackageManifest expected,
        IReadOnlyList<SourceFact> sources)
    {
        using var archive = ZipFile.OpenRead(destination);
        var entry = archive.GetEntry($"{expected.PackageId}/work-package.json")
            ?? throw new BusinessAdapterException("existing_package_invalid");
        BusinessWorkPackageManifest? manifest;
        using (var stream = entry.Open())
        {
            manifest = JsonSerializer.Deserialize<BusinessWorkPackageManifest>(stream, JsonOptions);
        }
        if (manifest is null
            || manifest.PackageId != expected.PackageId
            || manifest.IdempotencyKey != expected.IdempotencyKey
            || manifest.AnalysisProfile != expected.AnalysisProfile
            || manifest.Inputs.Length != sources.Count)
        {
            throw new BusinessAdapterException("existing_package_identity_conflict");
        }
        for (var index = 0; index < sources.Count; index++)
        {
            var input = manifest.Inputs[index];
            if (input.Path != sources[index].ArchivePath || input.Sha256 != sources[index].Sha256)
            {
                throw new BusinessAdapterException("existing_package_identity_conflict");
            }
        }
    }

    private string ComputeIdentity(string projectKey, string objective, IReadOnlyList<SourceFact> sources)
    {
        var builder = new StringBuilder();
        builder.Append(AdapterProfile).Append('\n')
            .Append(projectKey).Append('\n')
            .Append(objective).Append('\n');
        foreach (var source in sources)
        {
            builder.Append(source.ArchivePath).Append('|')
                .Append(source.Sha256).Append('|')
                .Append(source.SizeBytes).Append('\n');
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(builder.ToString()))).ToLowerInvariant();
    }

    private static Guid DeterministicGuid(string sha256)
    {
        var bytes = Convert.FromHexString(sha256[..32]);
        bytes[7] = (byte)((bytes[7] & 0x0F) | 0x50);
        bytes[8] = (byte)((bytes[8] & 0x3F) | 0x80);
        return new Guid(bytes);
    }

    private static string RequireBoundedText(string value, int minimum, int maximum, string code)
    {
        var trimmed = value?.Trim() ?? string.Empty;
        if (trimmed.Length < minimum || trimmed.Length > maximum)
        {
            throw new BusinessAdapterException(code);
        }
        return trimmed;
    }

    private static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars().ToHashSet();
        var filtered = new string(name.Select(character => invalid.Contains(character) ? '_' : character).ToArray());
        if (filtered is "." or ".." || string.IsNullOrWhiteSpace(filtered))
        {
            return "input.dat";
        }
        return filtered;
    }

    private static void RejectReparsePoint(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw new BusinessAdapterException("reparse_point_rejected");
        }
    }

    private static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private sealed record SourceFact(string FullPath, string ArchivePath, string Sha256, long SizeBytes);
}
