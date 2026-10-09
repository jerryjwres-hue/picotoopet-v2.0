using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

internal sealed record VerifiedC004Source(
    FinalVideoArtifact Artifact,
    VerifiedMasterVisual Visual);

internal sealed record VerifiedOverlaySource(
    VerifiedMasterVisual Visual,
    string ManifestSha256);

internal sealed record VerifiedNarrationSource(
    IReadOnlyList<VerifiedMasterNarrationSegment> Segments,
    IReadOnlyList<MasterNarrationSegmentIdentity> IdentitySegments,
    string ManifestSha256);

/// <summary>只读重验 C004/C007B/C008B 的精确托管路径、清单、字节与媒体事实。</summary>
internal sealed class PostProductionMasterSourceVerifier
{
    private const int MaximumManifestBytes = 256 * 1024;
    private const int MaximumWavBytes = 32 * 1024 * 1024;
    private const long MaximumNarrationBytes = 256L * 1024 * 1024;
    private static readonly JsonSerializerOptions StrictJson = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };
    private readonly string _finalRoot;
    private readonly string _narrationRoot;
    private readonly string _overlayRoot;

    public PostProductionMasterSourceVerifier(string finalRoot, string narrationRoot, string overlayRoot)
    {
        _finalRoot = RequireAbsolute(finalRoot);
        _narrationRoot = RequireAbsolute(narrationRoot);
        _overlayRoot = RequireAbsolute(overlayRoot);
    }

    public async Task<VerifiedC004Source> VerifyFinalVideoAsync(
        FinalVideoArtifact artifact,
        CancellationToken cancellationToken)
    {
        try
        {
            ArgumentNullException.ThrowIfNull(artifact);
            EnsureExistingRoot(_finalRoot);
            if (!SafeId(artifact.ProductionJobId, 120)
                || !SafeId(artifact.ProductionPackageId, 160)
                || !Sha(artifact.ProductionPackageDigest)
                || !Sha(artifact.Sha256)
                || artifact.Bytes <= 0)
            {
                throw VisualInvalid();
            }

            var identity = HashText(artifact.ProductionJobId)[..32];
            var fileName = $"final-{identity}.mp4";
            var manifestName = $"final-{identity}.final-video.json";
            var expectedFile = ProductionLocalEnvironment.ResolveUnderRoot(
                _finalRoot, fileName, requireExistingFile: false);
            var expectedManifest = ProductionLocalEnvironment.ResolveUnderRoot(
                _finalRoot, manifestName, requireExistingFile: false);
            RequireExactPath(expectedFile, artifact.FilePath, MasterCompositionException.VisualInvalid);
            RequireExactPath(expectedManifest, artifact.ManifestPath, MasterCompositionException.VisualInvalid);
            RequireOrdinary(_finalRoot, expectedFile, artifact.Bytes, MasterCompositionException.VisualInvalid);
            RequireOrdinary(_finalRoot, expectedManifest, null, MasterCompositionException.VisualInvalid);
            var manifest = await ReadManifestAsync<FinalVideoManifest>(
                expectedManifest, cancellationToken, MasterCompositionException.VisualInvalid).ConfigureAwait(false);
            var actualSha = await ProductionLocalEnvironment.Sha256FileAsync(expectedFile, cancellationToken)
                .ConfigureAwait(false);
            if (manifest.SchemaVersion != "1.0"
                || manifest.ProductionJobId != artifact.ProductionJobId
                || manifest.ProductionPackageId != artifact.ProductionPackageId
                || manifest.ProductionPackageDigest != artifact.ProductionPackageDigest
                || manifest.SourceOutputSha256 is not { Length: > 0 }
                || manifest.SourceOutputSha256.Any(value => !Sha(value))
                || manifest.FinalFileName != fileName
                || manifest.FinalSha256 != artifact.Sha256
                || manifest.FinalSha256 != actualSha
                || manifest.FinalBytes != artifact.Bytes)
            {
                throw VisualInvalid();
            }
            return new VerifiedC004Source(
                artifact,
                new VerifiedMasterVisual(expectedFile, actualSha, artifact.Bytes,
                    PostProductionMasterProfiles.C004VisualKind));
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (IsDurableFailure(exception))
        {
            throw VisualInvalid(exception);
        }
    }

    public async Task<VerifiedOverlaySource> VerifyOverlayAsync(
        TextOverlayArtifact artifact,
        FinalVideoArtifact c004,
        CaptionOverlayPlanResponseRecord response,
        CancellationToken cancellationToken)
    {
        try
        {
            ArgumentNullException.ThrowIfNull(artifact);
            EnsureExistingRoot(_overlayRoot);
            if (artifact.Passthrough
                || artifact.ManifestPath is null
                || artifact.ProductionJobId != c004.ProductionJobId
                || artifact.SourceFinalSha256 != c004.Sha256
                || artifact.CaptionOverlayPlanDigest != response.CaptionOverlayPlanDigest
                || artifact.OutputProfileId != response.Plan.OutputProfileId
                || !Sha(artifact.Sha256)
                || artifact.Bytes <= 0)
            {
                throw VisualInvalid();
            }

            var manifestPath = Path.GetFullPath(artifact.ManifestPath);
            var outputPath = Path.GetFullPath(artifact.FilePath);
            RequireOrdinary(_overlayRoot, manifestPath, null, MasterCompositionException.VisualInvalid);
            RequireOrdinary(_overlayRoot, outputPath, artifact.Bytes, MasterCompositionException.VisualInvalid);
            var manifest = await ReadManifestAsync<TextOverlayManifest>(
                manifestPath, cancellationToken, MasterCompositionException.VisualInvalid).ConfigureAwait(false);
            if (!Sha(manifest.ArtifactIdentitySha256))
            {
                throw VisualInvalid();
            }
            var expectedOutputName = $"overlay-{manifest.ArtifactIdentitySha256[..32]}.mp4";
            var expectedManifestName = $"overlay-{manifest.ArtifactIdentitySha256[..32]}.text-overlay.json";
            RequireExactPath(
                ProductionLocalEnvironment.ResolveUnderRoot(_overlayRoot, expectedOutputName, false),
                outputPath,
                MasterCompositionException.VisualInvalid);
            RequireExactPath(
                ProductionLocalEnvironment.ResolveUnderRoot(_overlayRoot, expectedManifestName, false),
                manifestPath,
                MasterCompositionException.VisualInvalid);

            if (manifest.SchemaVersion != WindowsCaptionOverlayService.ManifestSchemaVersion
                || manifest.ProductionJobId != c004.ProductionJobId
                || manifest.ProductionPackageId != c004.ProductionPackageId
                || manifest.ProductionPackageDigest != c004.ProductionPackageDigest
                || manifest.SourceFinalSha256 != c004.Sha256
                || manifest.CaptionOverlayPlanDigest != response.CaptionOverlayPlanDigest
                || manifest.OutputProfileId != response.Plan.OutputProfileId
                || manifest.OverlayStyleProfileId != response.Plan.OverlayStyleProfileId
                || manifest.FontProfileId != response.Plan.FontProfileId
                || manifest.RendererProfileId != WindowsCaptionOverlayRenderer.RendererProfileId
                || manifest.ArtifactIdentitySha256 != ComputeOverlayArtifactIdentity(manifest)
                || manifest.OutputFileName != expectedOutputName
                || manifest.OutputSha256 != artifact.Sha256
                || manifest.OutputBytes != artifact.Bytes
                || manifest.Passthrough
                || !OverlayCuesMatch(manifest.Cues, response.Plan.Overlays))
            {
                throw VisualInvalid();
            }
            var actualSha = await ProductionLocalEnvironment.Sha256FileAsync(outputPath, cancellationToken)
                .ConfigureAwait(false);
            if (actualSha != artifact.Sha256)
            {
                throw VisualInvalid();
            }
            var manifestSha = await ProductionLocalEnvironment.Sha256FileAsync(manifestPath, cancellationToken)
                .ConfigureAwait(false);
            return new VerifiedOverlaySource(
                new VerifiedMasterVisual(outputPath, actualSha, artifact.Bytes,
                    PostProductionMasterProfiles.C008BVisualKind),
                manifestSha);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (IsDurableFailure(exception))
        {
            throw VisualInvalid(exception);
        }
    }

    public async Task<VerifiedNarrationSource> VerifyNarrationAsync(
        NarrationArtifact artifact,
        NarrationPlanResponseRecord response,
        CancellationToken cancellationToken)
    {
        try
        {
            ArgumentNullException.ThrowIfNull(artifact);
            EnsureExistingRoot(_narrationRoot);
            var plan = response.Plan;
            var expectedDirectory = ResolveNarrationJobDirectory(plan.ProductionJobId);
            var expectedManifest = Path.Combine(expectedDirectory, "narration-manifest.json");
            RequireExactPath(expectedManifest, artifact.ManifestPath, MasterCompositionException.NarrationInvalid);
            RequireOrdinary(_narrationRoot, expectedManifest, null, MasterCompositionException.NarrationInvalid);
            var manifest = await ReadManifestAsync<NarrationManifest>(
                expectedManifest, cancellationToken, MasterCompositionException.NarrationInvalid).ConfigureAwait(false);
            if (manifest.SchemaVersion != "1.0"
                || manifest.ProductionJobId != plan.ProductionJobId
                || manifest.CreativePackageId != plan.CreativePackageId
                || manifest.CreativePackageDigest != plan.CreativePackageDigest
                || manifest.ProductionPlanDigest != plan.ProductionPlanDigest
                || manifest.NarrationPlanDigest != response.NarrationPlanDigest
                || manifest.TtsProfileId != plan.TtsProfileId
                || manifest.VoiceProfileId != plan.VoiceProfileId
                || !Sha(manifest.ResolvedVoiceIdentitySha256)
                || manifest.Segments.Count != plan.Segments.Length
                || artifact.Segments.Count != plan.Segments.Length)
            {
                throw NarrationInvalid();
            }

            var verified = new List<VerifiedMasterNarrationSegment>(plan.Segments.Length);
            var identities = new List<MasterNarrationSegmentIdentity>(plan.Segments.Length);
            var expectedEntries = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "narration-manifest.json",
            };
            long totalBytes = 0;
            for (var index = 0; index < plan.Segments.Length; index++)
            {
                var expected = plan.Segments[index];
                var durable = manifest.Segments[index];
                var publicSegment = artifact.Segments[index];
                var expectedName = NarrationFileName(expected);
                if (durable.SegmentId != expected.SegmentId
                    || durable.BeatId != expected.BeatId
                    || durable.Order != expected.Order
                    || durable.TextSha256 != expected.TextSha256
                    || durable.StartMs != expected.StartMs
                    || durable.EndMs != expected.EndMs
                    || durable.WavFileName != expectedName
                    || publicSegment.FileName != expectedName)
                {
                    throw NarrationInvalid();
                }
                var wavPath = Path.Combine(expectedDirectory, expectedName);
                RequireExactPath(wavPath, publicSegment.WavPath, MasterCompositionException.NarrationInvalid);
                RequireOrdinary(_narrationRoot, wavPath, durable.WavBytes, MasterCompositionException.NarrationInvalid);
                if (durable.WavBytes is <= 0 or > MaximumWavBytes || !Sha(durable.WavSha256))
                {
                    throw NarrationInvalid();
                }
                totalBytes = checked(totalBytes + durable.WavBytes);
                if (totalBytes > MaximumNarrationBytes)
                {
                    throw NarrationInvalid();
                }
                var wav = await File.ReadAllBytesAsync(wavPath, cancellationToken).ConfigureAwait(false);
                var facts = ParseWav(wav);
                var wavSha = Convert.ToHexString(SHA256.HashData(wav)).ToLowerInvariant();
                if (wavSha != durable.WavSha256
                    || facts.SampleRate != durable.WavSampleRate
                    || facts.Channels != durable.WavChannels
                    || facts.BitsPerSample != durable.WavBits
                    || facts.DurationMs != durable.SynthesizedDurationMs)
                {
                    throw NarrationInvalid();
                }
                var windowMs = expected.EndMs - expected.StartMs;
                var sampleFrames = facts.SampleFrames;
                if (sampleFrames * 1_000L > windowMs * facts.SampleRate)
                {
                    throw new MasterCompositionException(MasterCompositionException.NarrationSegmentTooLong);
                }
                expectedEntries.Add(expectedName);
                verified.Add(new VerifiedMasterNarrationSegment(
                    expected.SegmentId, expected.Order, wavPath, wavSha, durable.WavBytes,
                    expected.StartMs, expected.EndMs, facts.DurationMs, facts.SampleFrames,
                    facts.SampleRate, facts.Channels));
                identities.Add(new MasterNarrationSegmentIdentity(
                    expected.SegmentId, expected.BeatId, expected.Order, expected.TextSha256,
                    expected.StartMs, expected.EndMs, wavSha, durable.WavBytes, facts.DurationMs,
                    facts.SampleFrames, facts.SampleRate, facts.Channels, facts.BitsPerSample));
            }
            var actualEntries = Directory.EnumerateFileSystemEntries(expectedDirectory)
                .Select(path => Path.GetFileName(path) ?? string.Empty)
                .ToHashSet(StringComparer.OrdinalIgnoreCase);
            if (!actualEntries.SetEquals(expectedEntries))
            {
                throw NarrationInvalid();
            }
            var manifestSha = await ProductionLocalEnvironment.Sha256FileAsync(expectedManifest, cancellationToken)
                .ConfigureAwait(false);
            return new VerifiedNarrationSource(verified, identities, manifestSha);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (MasterCompositionException)
        {
            throw;
        }
        catch (Exception exception) when (IsDurableFailure(exception))
        {
            throw NarrationInvalid(exception);
        }
    }

    internal static string ComputeOverlayPlanDigest(CaptionOverlayPlanRecord plan)
    {
        var node = JsonSerializer.SerializeToNode(plan)
            ?? throw new MasterCompositionException(MasterCompositionException.InputInvalid);
        return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    }

    private string ResolveNarrationJobDirectory(string jobId)
    {
        var safe = new string(jobId.Select(character => char.IsAsciiLetterOrDigit(character) || character is '-' or '_'
            ? character : '_').Take(40).ToArray());
        return ProductionLocalEnvironment.ResolveUnderRoot(
            _narrationRoot, $"{safe}-{HashText(jobId)[..16]}", requireExistingFile: false);
    }

    private static string NarrationFileName(NarrationSegmentPlanRecord segment)
    {
        var safe = new string(segment.SegmentId.Select(character => char.IsAsciiLetterOrDigit(character)
            || character is '-' or '_' ? character : '_').Take(40).ToArray());
        return $"{segment.Order:D3}-{safe}-{segment.TextSha256}.wav";
    }

    private static WavFacts ParseWav(ReadOnlySpan<byte> wav)
    {
        if (wav.Length is < 44 or > MaximumWavBytes
            || !wav[..4].SequenceEqual("RIFF"u8)
            || !wav.Slice(8, 4).SequenceEqual("WAVE"u8)
            || BinaryPrimitives.ReadUInt32LittleEndian(wav.Slice(4, 4)) + 8u != wav.Length)
        {
            throw NarrationInvalid();
        }
        short format = 0;
        short channels = 0;
        short bits = 0;
        short blockAlign = 0;
        int sampleRate = 0;
        int byteRate = 0;
        int dataBytes = 0;
        var foundFormat = false;
        var foundData = false;
        var offset = 12;
        while (offset <= wav.Length - 8)
        {
            var unsignedSize = BinaryPrimitives.ReadUInt32LittleEndian(wav.Slice(offset + 4, 4));
            if (unsignedSize > int.MaxValue)
            {
                throw NarrationInvalid();
            }
            var chunkSize = (int)unsignedSize;
            var dataOffset = offset + 8;
            if (dataOffset > wav.Length - chunkSize)
            {
                throw NarrationInvalid();
            }
            var id = wav.Slice(offset, 4);
            if (id.SequenceEqual("fmt "u8))
            {
                if (foundFormat || chunkSize < 16)
                {
                    throw NarrationInvalid();
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
                    throw NarrationInvalid();
                }
                foundData = true;
                dataBytes = chunkSize;
            }
            offset = checked(dataOffset + chunkSize + (chunkSize & 1));
        }
        if (!foundFormat || !foundData || format != 1 || channels is not (1 or 2)
            || sampleRate is < 8_000 or > 48_000 || bits != 16
            || blockAlign != channels * 2 || byteRate != sampleRate * blockAlign
            || dataBytes <= 0 || dataBytes % blockAlign != 0)
        {
            throw NarrationInvalid();
        }
        var frames = dataBytes / blockAlign;
        var durationMs = frames * 1_000L / sampleRate;
        if (durationMs <= 0)
        {
            throw NarrationInvalid();
        }
        return new WavFacts(sampleRate, channels, bits, frames, durationMs);
    }

    private static bool OverlayCuesMatch(
        IReadOnlyList<TextOverlayManifestCue> durable,
        IReadOnlyList<CaptionOverlayCueRecord> expected)
    {
        if (durable.Count != expected.Count)
        {
            return false;
        }
        for (var index = 0; index < expected.Count; index++)
        {
            var left = durable[index];
            var right = expected[index];
            if (left.CueId != right.CueId || left.BeatId != right.BeatId || left.Order != right.Order
                || left.TextSha256 != right.TextSha256 || left.StartMs != right.StartMs
                || left.EndMs != right.EndMs || Path.GetFileName(left.ResolvedFontName) != left.ResolvedFontName
                || !Sha(left.ResolvedFontIdentitySha256))
            {
                return false;
            }
        }
        return true;
    }

    private static string ComputeOverlayArtifactIdentity(TextOverlayManifest manifest)
    {
        var fonts = new JsonArray();
        foreach (var identity in manifest.Cues.Select(static cue => cue.ResolvedFontIdentitySha256)
                     .Distinct(StringComparer.Ordinal)
                     .Order(StringComparer.Ordinal))
        {
            fonts.Add(identity);
        }
        var node = new JsonObject
        {
            ["renderer_profile_id"] = manifest.RendererProfileId,
            ["source_final_sha256"] = manifest.SourceFinalSha256,
            ["caption_overlay_plan_digest"] = manifest.CaptionOverlayPlanDigest,
            ["output_profile_id"] = manifest.OutputProfileId,
            ["overlay_style_profile_id"] = manifest.OverlayStyleProfileId,
            ["font_profile_id"] = manifest.FontProfileId,
            ["font_identity_sha256"] = fonts,
        };
        return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    }

    private static async Task<T> ReadManifestAsync<T>(
        string path,
        CancellationToken cancellationToken,
        string code)
        where T : class
    {
        var length = new FileInfo(path).Length;
        if (length is <= 0 or > MaximumManifestBytes)
        {
            throw new MasterCompositionException(code);
        }
        var bytes = await File.ReadAllBytesAsync(path, cancellationToken).ConfigureAwait(false);
        return JsonSerializer.Deserialize<T>(bytes, StrictJson) ?? throw new MasterCompositionException(code);
    }

    private static void EnsureExistingRoot(string root)
    {
        if (!Directory.Exists(root))
        {
            throw new DirectoryNotFoundException();
        }
        ProductionLocalEnvironment.AssertNoLinkEscape(root, root);
    }

    private static void RequireOrdinary(string root, string path, long? expectedBytes, string code)
    {
        ProductionLocalEnvironment.AssertNoLinkEscape(root, path);
        if (!ProductionLocalEnvironment.IsOrdinaryFile(path)
            || (expectedBytes is long bytes && new FileInfo(path).Length != bytes))
        {
            throw new MasterCompositionException(code);
        }
    }

    private static void RequireExactPath(string expected, string actual, string code)
    {
        if (string.IsNullOrWhiteSpace(actual)
            || !string.Equals(Path.GetFullPath(actual), Path.GetFullPath(expected), StringComparison.OrdinalIgnoreCase))
        {
            throw new MasterCompositionException(code);
        }
    }

    private static string RequireAbsolute(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
        {
            throw new ArgumentException("MASTER_INPUT_INVALID");
        }
        return Path.GetFullPath(path);
    }

    private static bool SafeId(string? value, int maximum) =>
        value is { Length: > 0 } && value.Length <= maximum;

    private static bool Sha(string? value) => value is { Length: 64 }
        && value.All(static character => character is (>= '0' and <= '9') or (>= 'a' and <= 'f'));

    private static string HashText(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();

    private static bool IsDurableFailure(Exception exception) => exception is IOException
        or UnauthorizedAccessException or JsonException or ArgumentException or NotSupportedException
        or OverflowException or CryptographicException or NullReferenceException;

    private static MasterCompositionException VisualInvalid(Exception? inner = null) =>
        new(MasterCompositionException.VisualInvalid, inner);

    private static MasterCompositionException NarrationInvalid(Exception? inner = null) =>
        new(MasterCompositionException.NarrationInvalid, inner);

    private sealed record WavFacts(
        int SampleRate,
        short Channels,
        short BitsPerSample,
        long SampleFrames,
        long DurationMs);

    private sealed record FinalVideoManifest(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("production_job_id")] string ProductionJobId,
        [property: JsonPropertyName("production_package_id")] string ProductionPackageId,
        [property: JsonPropertyName("production_package_digest")] string ProductionPackageDigest,
        [property: JsonPropertyName("source_output_sha256")] string[] SourceOutputSha256,
        [property: JsonPropertyName("final_file_name")] string FinalFileName,
        [property: JsonPropertyName("final_sha256")] string FinalSha256,
        [property: JsonPropertyName("final_bytes")] long FinalBytes,
        [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

    private sealed record TextOverlayManifestCue(
        [property: JsonPropertyName("cue_id")] string CueId,
        [property: JsonPropertyName("beat_id")] string BeatId,
        [property: JsonPropertyName("order")] int Order,
        [property: JsonPropertyName("text_sha256")] string TextSha256,
        [property: JsonPropertyName("start_ms")] int StartMs,
        [property: JsonPropertyName("end_ms")] int EndMs,
        [property: JsonPropertyName("resolved_font_name")] string ResolvedFontName,
        [property: JsonPropertyName("resolved_font_identity_sha256")] string ResolvedFontIdentitySha256);

    private sealed record TextOverlayManifest(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("production_job_id")] string ProductionJobId,
        [property: JsonPropertyName("source_production_package_id")] string ProductionPackageId,
        [property: JsonPropertyName("source_production_package_digest")] string ProductionPackageDigest,
        [property: JsonPropertyName("source_final_sha256")] string SourceFinalSha256,
        [property: JsonPropertyName("caption_overlay_plan_digest")] string CaptionOverlayPlanDigest,
        [property: JsonPropertyName("output_profile_id")] string OutputProfileId,
        [property: JsonPropertyName("overlay_style_profile_id")] string OverlayStyleProfileId,
        [property: JsonPropertyName("font_profile_id")] string FontProfileId,
        [property: JsonPropertyName("renderer_profile_id")] string RendererProfileId,
        [property: JsonPropertyName("artifact_identity_sha256")] string ArtifactIdentitySha256,
        [property: JsonPropertyName("cues")] IReadOnlyList<TextOverlayManifestCue> Cues,
        [property: JsonPropertyName("output_file_name")] string OutputFileName,
        [property: JsonPropertyName("output_sha256")] string OutputSha256,
        [property: JsonPropertyName("output_bytes")] long OutputBytes,
        [property: JsonPropertyName("passthrough")] bool Passthrough,
        [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

    private sealed record NarrationManifest(
        [property: JsonPropertyName("schema_version")] string SchemaVersion,
        [property: JsonPropertyName("production_job_id")] string ProductionJobId,
        [property: JsonPropertyName("creative_package_id")] string CreativePackageId,
        [property: JsonPropertyName("creative_package_digest")] string CreativePackageDigest,
        [property: JsonPropertyName("production_plan_digest")] string ProductionPlanDigest,
        [property: JsonPropertyName("narration_plan_digest")] string NarrationPlanDigest,
        [property: JsonPropertyName("tts_profile_id")] string TtsProfileId,
        [property: JsonPropertyName("voice_profile_id")] string VoiceProfileId,
        [property: JsonPropertyName("resolved_voice_name")] string ResolvedVoiceName,
        [property: JsonPropertyName("resolved_voice_culture")] string ResolvedVoiceCulture,
        [property: JsonPropertyName("resolved_voice_identity_sha256")] string ResolvedVoiceIdentitySha256,
        [property: JsonPropertyName("segments")] IReadOnlyList<NarrationManifestSegment> Segments,
        [property: JsonPropertyName("created_at")] DateTimeOffset CreatedAt);

    private sealed record NarrationManifestSegment(
        [property: JsonPropertyName("segment_id")] string SegmentId,
        [property: JsonPropertyName("beat_id")] string BeatId,
        [property: JsonPropertyName("order")] int Order,
        [property: JsonPropertyName("text_sha256")] string TextSha256,
        [property: JsonPropertyName("start_ms")] long StartMs,
        [property: JsonPropertyName("end_ms")] long EndMs,
        [property: JsonPropertyName("wav_file_name")] string WavFileName,
        [property: JsonPropertyName("wav_sha256")] string WavSha256,
        [property: JsonPropertyName("wav_bytes")] long WavBytes,
        [property: JsonPropertyName("wav_sample_rate")] int WavSampleRate,
        [property: JsonPropertyName("wav_channels")] short WavChannels,
        [property: JsonPropertyName("wav_bits")] short WavBits,
        [property: JsonPropertyName("synthesized_duration_ms")] long SynthesizedDurationMs);
}
