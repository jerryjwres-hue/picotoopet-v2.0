using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

// 本地旁白合成服务只使用受控 OneCore 语音与托管 WAV 产物，不引入云端或任意模型。
internal sealed record NarrationInstalledVoice(string Id, string DisplayName, string Culture);

internal interface INarrationSpeechBackend
{
    IReadOnlyList<NarrationInstalledVoice> GetInstalledVoices();
    Task<byte[]> SynthesizeAsync(
        NarrationInstalledVoice voice,
        string text,
        CancellationToken cancellationToken);
}

public sealed class NarrationSynthesisException : Exception
{
    public NarrationSynthesisException(string code) : base(code)
    {
    }
}

internal static class NarrationVoiceSelector
{
    public static NarrationInstalledVoice Select(
        IReadOnlyList<NarrationInstalledVoice> voices,
        IReadOnlyList<NarrationSegmentPlanRecord> segments)
    {
        var target = segments.Any(segment => segment.Text.EnumerateRunes().Any(IsHan)) ? "zh-CN" : "en-US";
        var family = target[..2];
        var selected = voices
            .Where(voice => string.Equals(voice.Culture, family, StringComparison.OrdinalIgnoreCase)
                || voice.Culture.StartsWith(family + "-", StringComparison.OrdinalIgnoreCase))
            .OrderBy(voice => string.Equals(voice.Culture, target, StringComparison.OrdinalIgnoreCase) ? 0 : 1)
            .ThenBy(voice => voice.DisplayName, StringComparer.Ordinal)
            .ThenBy(voice => voice.Id, StringComparer.Ordinal)
            .FirstOrDefault();
        return selected ?? throw new NarrationSynthesisException("NARRATION_VOICE_UNAVAILABLE");
    }

    private static bool IsHan(Rune rune) => rune.Value is >= 0x3400 and <= 0x4dbf
        or >= 0x4e00 and <= 0x9fff
        or >= 0xf900 and <= 0xfaff
        or >= 0x20000 and <= 0x2ebef
        or >= 0x2f800 and <= 0x2fa1f
        or >= 0x30000 and <= 0x323af;
}

internal sealed record NarrationWavFacts(int SampleRate, short Channels, short BitsPerSample, long DurationMs);

internal static class NarrationWavValidator
{
    public const int MaximumBytes = 32 * 1024 * 1024;

    public static NarrationWavFacts Validate(ReadOnlySpan<byte> wav)
    {
        if (wav.Length is < 44 or > MaximumBytes
            || !wav[..4].SequenceEqual("RIFF"u8)
            || !wav.Slice(8, 4).SequenceEqual("WAVE"u8)
            || BinaryPrimitives.ReadUInt32LittleEndian(wav.Slice(4, 4)) + 8u != wav.Length)
        {
            throw Invalid();
        }

        short format = 0;
        short channels = 0;
        int sampleRate = 0;
        short bits = 0;
        short blockAlign = 0;
        int byteRate = 0;
        int dataBytes = 0;
        var foundFormat = false;
        var foundData = false;
        var offset = 12;
        while (offset <= wav.Length - 8)
        {
            var unsignedChunkSize = BinaryPrimitives.ReadUInt32LittleEndian(wav.Slice(offset + 4, 4));
            if (unsignedChunkSize > int.MaxValue)
            {
                throw Invalid();
            }
            var chunkSize = (int)unsignedChunkSize;
            var dataOffset = offset + 8;
            if (chunkSize < 0 || dataOffset > wav.Length - chunkSize)
            {
                throw Invalid();
            }
            var id = wav.Slice(offset, 4);
            if (id.SequenceEqual("fmt "u8))
            {
                if (foundFormat || chunkSize < 16)
                {
                    throw Invalid();
                }
                foundFormat = true;
                format = BinaryPrimitives.ReadInt16LittleEndian(wav.Slice(dataOffset, 2));
                channels = BinaryPrimitives.ReadInt16LittleEndian(wav.Slice(dataOffset + 2, 2));
                sampleRate = BinaryPrimitives.ReadInt32LittleEndian(wav.Slice(dataOffset + 4, 4));
                byteRate = BinaryPrimitives.ReadInt32LittleEndian(wav.Slice(dataOffset + 8, 4));
                blockAlign = BinaryPrimitives.ReadInt16LittleEndian(wav.Slice(dataOffset + 12, 2));
                bits = BinaryPrimitives.ReadInt16LittleEndian(wav.Slice(dataOffset + 14, 2));
            }
            else if (id.SequenceEqual("data"u8))
            {
                if (foundData)
                {
                    throw Invalid();
                }
                foundData = true;
                dataBytes = chunkSize;
            }
            offset = checked(dataOffset + chunkSize + (chunkSize & 1));
        }

        if (format != 1 || channels is not (1 or 2) || sampleRate is < 8_000 or > 48_000
            || bits != 16 || dataBytes <= 0
            || blockAlign != channels * (bits / 8)
            || byteRate != sampleRate * blockAlign
            || dataBytes % blockAlign != 0)
        {
            throw Invalid();
        }
        var bytesPerSecond = (long)sampleRate * channels * (bits / 8);
        var duration = dataBytes * 1_000L / bytesPerSecond;
        if (duration <= 0)
        {
            throw Invalid();
        }
        return new NarrationWavFacts(sampleRate, channels, bits, duration);
    }

    private static NarrationSynthesisException Invalid() => new("NARRATION_WAV_INVALID");
}

public sealed record NarrationArtifactSegment(string FileName, string WavPath);

public sealed record NarrationArtifact(string ManifestPath, IReadOnlyList<NarrationArtifactSegment> Segments);

public sealed class WindowsNarrationSynthesisService
{
    public const int TimingToleranceMs = 250;
    private const string ManifestFileName = "narration-manifest.json";
    private const long MaximumArtifactBytes = 256L * 1024 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    private readonly INarrationSpeechBackend backend;
    private readonly TimeSpan segmentTimeout;

    internal WindowsNarrationSynthesisService(
        string managedRoot,
        INarrationSpeechBackend backend,
        TimeSpan segmentTimeout)
    {
        if (string.IsNullOrWhiteSpace(managedRoot) || !Path.IsPathFullyQualified(managedRoot))
        {
            throw new ArgumentException("Managed root must be absolute.", nameof(managedRoot));
        }
        if (segmentTimeout <= TimeSpan.Zero || segmentTimeout > TimeSpan.FromMinutes(2))
        {
            throw new ArgumentOutOfRangeException(nameof(segmentTimeout));
        }
        ManagedRoot = Path.GetFullPath(managedRoot);
        this.backend = backend;
        this.segmentTimeout = segmentTimeout;
    }

    public string ManagedRoot { get; }

    public static WindowsNarrationSynthesisService CreateDefault() => new(
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PicotooPet", "Narration", "v1"),
        new WindowsMediaSpeechBackend(),
        TimeSpan.FromSeconds(60));

    public async Task<NarrationArtifact> SynthesizeAsync(
        NarrationPlanResponseRecord response,
        CancellationToken cancellationToken)
    {
        try
        {
            NarrationPlanContract.Validate(response);
        }
        catch (NarrationPlanContractException)
        {
            throw new NarrationSynthesisException("NARRATION_PLAN_INVALID");
        }

        var plan = response.Plan;
        var voice = ResolveVoice(plan);
        var voiceIdentity = Sha(voice.Id);
        var directory = ResolveJobDirectory(plan.ProductionJobId);
        var manifestPath = Path.Combine(directory, ManifestFileName);

        if (HasDurableEntries(directory))
        {
            return Reuse(response, voice, voiceIdentity, directory, manifestPath);
        }

        var temporary = new List<string>();
        var promoted = new List<string>();
        try
        {
            Directory.CreateDirectory(directory);
            var segmentManifests = new List<NarrationArtifactSegmentManifest>();
            long totalBytes = 0;
            foreach (var segment in plan.Segments)
            {
                cancellationToken.ThrowIfCancellationRequested();
                byte[] bytes;
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                timeout.CancelAfter(segmentTimeout);
                try
                {
                    bytes = await backend.SynthesizeAsync(voice, segment.Text, timeout.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                {
                    throw new NarrationSynthesisException("NARRATION_TTS_TIMEOUT");
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch (NarrationSynthesisException)
                {
                    throw;
                }
                catch
                {
                    throw new NarrationSynthesisException("NARRATION_TTS_FAILED");
                }

                var facts = NarrationWavValidator.Validate(bytes);
                totalBytes = checked(totalBytes + bytes.LongLength);
                if (totalBytes > MaximumArtifactBytes)
                {
                    throw new NarrationSynthesisException("NARRATION_WAV_INVALID");
                }
                if (facts.DurationMs > segment.EndMs - segment.StartMs + TimingToleranceMs)
                {
                    throw new NarrationSynthesisException("NARRATION_SEGMENT_TOO_LONG");
                }
                var fileName = FileName(segment);
                var finalPath = Path.Combine(directory, fileName);
                var tempPath = finalPath + $".{Guid.NewGuid():N}.tmp";
                await File.WriteAllBytesAsync(tempPath, bytes, cancellationToken).ConfigureAwait(false);
                temporary.Add(tempPath);
                segmentManifests.Add(new NarrationArtifactSegmentManifest(
                    segment.SegmentId, segment.BeatId, segment.Order, segment.TextSha256,
                    segment.StartMs, segment.EndMs, fileName, Sha(bytes), bytes.LongLength,
                    facts.SampleRate, facts.Channels, facts.BitsPerSample, facts.DurationMs));
            }

            var manifest = new NarrationArtifactManifest(
                "1.0", plan.ProductionJobId, plan.CreativePackageId, plan.CreativePackageDigest,
                plan.ProductionPlanDigest, response.NarrationPlanDigest, plan.TtsProfileId,
                plan.VoiceProfileId, Bound(voice.DisplayName, 120), Bound(voice.Culture, 35),
                voiceIdentity, segmentManifests, DateTimeOffset.UtcNow);
            var manifestBytes = JsonSerializer.SerializeToUtf8Bytes(manifest, JsonOptions);
            var manifestTemp = manifestPath + $".{Guid.NewGuid():N}.tmp";
            await File.WriteAllBytesAsync(manifestTemp, manifestBytes, cancellationToken).ConfigureAwait(false);
            temporary.Add(manifestTemp);

            foreach (var segment in segmentManifests)
            {
                var tempPath = temporary.Single(path => Path.GetFileName(path).StartsWith(segment.WavFileName + ".", StringComparison.Ordinal));
                var finalPath = Path.Combine(directory, segment.WavFileName);
                File.Move(tempPath, finalPath);
                temporary.Remove(tempPath);
                promoted.Add(finalPath);
            }
            File.Move(manifestTemp, manifestPath);
            temporary.Remove(manifestTemp);
            return ToArtifact(manifest, directory, manifestPath);
        }
        catch (Exception exception)
        {
            foreach (var path in temporary.Concat(promoted))
            {
                TryDelete(path);
            }
            if (exception is IOException or UnauthorizedAccessException or JsonException
                or InvalidOperationException or OverflowException)
            {
                throw Conflict();
            }
            throw;
        }
    }

    private static NarrationArtifact Reuse(
        NarrationPlanResponseRecord response,
        NarrationInstalledVoice voice,
        string voiceIdentity,
        string directory,
        string manifestPath)
    {
        try
        {
            if (!File.Exists(manifestPath))
            {
                throw Conflict();
            }
            var bytes = File.ReadAllBytes(manifestPath);
            if (bytes.Length is 0 or > 256 * 1024)
            {
                throw Conflict();
            }
            var manifest = JsonSerializer.Deserialize<NarrationArtifactManifest>(bytes, JsonOptions)
                ?? throw Conflict();
            var plan = response.Plan;
            if (manifest.SchemaVersion != "1.0"
                || manifest.ProductionJobId != plan.ProductionJobId
                || manifest.CreativePackageId != plan.CreativePackageId
                || manifest.CreativePackageDigest != plan.CreativePackageDigest
                || manifest.ProductionPlanDigest != plan.ProductionPlanDigest
                || manifest.NarrationPlanDigest != response.NarrationPlanDigest
                || manifest.TtsProfileId != plan.TtsProfileId
                || manifest.VoiceProfileId != plan.VoiceProfileId
                || manifest.ResolvedVoiceName != Bound(voice.DisplayName, 120)
                || manifest.ResolvedVoiceCulture != Bound(voice.Culture, 35)
                || manifest.ResolvedVoiceIdentitySha256 != voiceIdentity
                || manifest.Segments.Count != plan.Segments.Length)
            {
                throw Conflict();
            }

            long totalBytes = 0;
            for (var index = 0; index < plan.Segments.Length; index++)
            {
                var expected = plan.Segments[index];
                var actual = manifest.Segments[index];
                var wavPath = Path.Combine(directory, actual.WavFileName);
                if (actual.SegmentId != expected.SegmentId || actual.BeatId != expected.BeatId
                    || actual.Order != expected.Order || actual.TextSha256 != expected.TextSha256
                    || actual.StartMs != expected.StartMs || actual.EndMs != expected.EndMs
                    || actual.WavFileName != FileName(expected) || Path.GetFileName(actual.WavFileName) != actual.WavFileName
                    || !File.Exists(wavPath))
                {
                    throw Conflict();
                }
                var wavLength = new FileInfo(wavPath).Length;
                if (wavLength is <= 0 or > NarrationWavValidator.MaximumBytes)
                {
                    throw Conflict();
                }
                totalBytes = checked(totalBytes + wavLength);
                if (totalBytes > MaximumArtifactBytes)
                {
                    throw Conflict();
                }
                var wav = File.ReadAllBytes(wavPath);
                var facts = NarrationWavValidator.Validate(wav);
                if (actual.WavBytes != wav.LongLength || actual.WavSha256 != Sha(wav)
                    || actual.WavSampleRate != facts.SampleRate || actual.WavChannels != facts.Channels
                    || actual.WavBits != facts.BitsPerSample || actual.SynthesizedDurationMs != facts.DurationMs
                    || facts.DurationMs > expected.EndMs - expected.StartMs + TimingToleranceMs)
                {
                    throw Conflict();
                }
            }
            return ToArtifact(manifest, directory, manifestPath);
        }
        catch (NarrationSynthesisException exception) when (exception.Message != "NARRATION_ARTIFACT_CONFLICT")
        {
            throw Conflict();
        }
        catch (JsonException)
        {
            throw Conflict();
        }
        catch (IOException)
        {
            throw Conflict();
        }
        catch (UnauthorizedAccessException)
        {
            throw Conflict();
        }
        catch (Exception exception) when (exception is NullReferenceException or NotSupportedException
            or OverflowException or ArgumentException)
        {
            throw Conflict();
        }
    }

    private NarrationInstalledVoice ResolveVoice(NarrationPlanRecord plan)
    {
        if (!plan.NarrationRequired)
        {
            return new NarrationInstalledVoice(string.Empty, string.Empty, string.Empty);
        }
        try
        {
            return NarrationVoiceSelector.Select(backend.GetInstalledVoices(), plan.Segments);
        }
        catch (NarrationSynthesisException)
        {
            throw;
        }
        catch
        {
            throw new NarrationSynthesisException("NARRATION_TTS_FAILED");
        }
    }

    private static bool HasDurableEntries(string directory)
    {
        try
        {
            return Directory.Exists(directory) && Directory.EnumerateFileSystemEntries(directory).Any();
        }
        catch (IOException)
        {
            throw Conflict();
        }
        catch (UnauthorizedAccessException)
        {
            throw Conflict();
        }
    }

    private string ResolveJobDirectory(string jobId)
    {
        var safe = new string(jobId.Select(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_'
            ? character : '_').Take(40).ToArray());
        var directory = Path.GetFullPath(Path.Combine(ManagedRoot, $"{safe}-{Sha(jobId)[..16]}"));
        var prefix = ManagedRoot.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!directory.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new NarrationSynthesisException("NARRATION_ARTIFACT_CONFLICT");
        }
        return directory;
    }

    private static NarrationArtifact ToArtifact(NarrationArtifactManifest manifest, string directory, string manifestPath) =>
        new(manifestPath, manifest.Segments.Select(segment =>
            new NarrationArtifactSegment(segment.WavFileName, Path.Combine(directory, segment.WavFileName))).ToArray());

    private static string FileName(NarrationSegmentPlanRecord segment)
    {
        var safe = new string(segment.SegmentId.Select(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_'
            ? character : '_').Take(40).ToArray());
        return $"{segment.Order:D3}-{safe}-{segment.TextSha256}.wav";
    }

    private static string Bound(string value, int maximum) => value.Length <= maximum ? value : value[..maximum];
    private static string Sha(string value) => Sha(Encoding.UTF8.GetBytes(value));
    private static string Sha(ReadOnlySpan<byte> value) => Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant();
    private static NarrationSynthesisException Conflict() => new("NARRATION_ARTIFACT_CONFLICT");
    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    private sealed record NarrationArtifactManifest(
        string SchemaVersion,
        string ProductionJobId,
        string CreativePackageId,
        string CreativePackageDigest,
        string ProductionPlanDigest,
        string NarrationPlanDigest,
        string TtsProfileId,
        string VoiceProfileId,
        string ResolvedVoiceName,
        string ResolvedVoiceCulture,
        string ResolvedVoiceIdentitySha256,
        IReadOnlyList<NarrationArtifactSegmentManifest> Segments,
        DateTimeOffset CreatedAt);

    private sealed record NarrationArtifactSegmentManifest(
        string SegmentId,
        string BeatId,
        int Order,
        string TextSha256,
        long StartMs,
        long EndMs,
        string WavFileName,
        string WavSha256,
        long WavBytes,
        int WavSampleRate,
        short WavChannels,
        short WavBits,
        long SynthesizedDurationMs);
}
