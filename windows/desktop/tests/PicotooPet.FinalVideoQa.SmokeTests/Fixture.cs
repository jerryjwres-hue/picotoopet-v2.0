using System.Buffers.Binary;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
namespace PicotooPet.FinalVideoQa.SmokeTests;
internal sealed class FixtureComposer(bool real) : IMasterVideoComposer
{
    public int Calls { get; private set; }

    public async Task ComposeAsync(MasterVideoCompositionRequest request, CancellationToken cancellationToken)
    {
        Calls++;
        if (real)
        {
            await new FixedFfmpegMasterVideoComposer(new FixedMasterVideoProcessRunner()).ComposeAsync(request, cancellationToken);
            return;
        }
        var visual = await File.ReadAllBytesAsync(request.Visual.Path, cancellationToken);
        await File.WriteAllBytesAsync(request.OutputPath,
            visual.Concat(Encoding.ASCII.GetBytes($"|master|{request.NarrationSegments.Count}")).ToArray(),
            cancellationToken);
    }
}

internal sealed class Fixture : IDisposable
{
    public const string NarrationText = "private narration words";
    public const string OverlayText = "private overlay words";
    private Fixture(string root, MasterCompositionInputV1 input, FixtureComposer composer,
        PostProductionMasterCompositorService service)
    {
        Root = root;
        Input = input;
        Composer = composer;
        Service = service;
    }

    public ProductionPlanRecord Plan { get; private set; } = null!;
    public string Root { get; }
    public string MasterRoot => Path.Combine(Root, "master");
    public MasterCompositionInputV1 Input { get; set; }
    public FixtureComposer Composer { get; }
    public PostProductionMasterCompositorService Service { get; }

    public static async Task<Fixture> CreateAsync(bool narrationRequired, bool overlaysRequired,
        int wavFrames = 24_000, long narrationWindowMs = 1_000, string profile = "video.landscape.v1", bool real = false)
    {
        var root = Path.Combine(Path.GetTempPath(), "picotoopet-c009a-" + Guid.NewGuid().ToString("N"));
        var finals = Path.Combine(root, "finals");
        var narration = Path.Combine(root, "narration");
        var overlays = Path.Combine(root, "overlays");
        var master = Path.Combine(root, "master");
        Directory.CreateDirectory(finals);
        Directory.CreateDirectory(narration);
        Directory.CreateDirectory(overlays);

        const string job = "job-1";
        const string package = "package-1";
        var packageDigest = Sha("package-digest");
        var creativeDigest = Sha("creative-digest");
        var dimensions = profile switch { "video.vertical.v1" => (480,832), "video.square.v1" => (640,640), _ => (832,480) };
        var plan = new ProductionPlanRecord("1.0", "production.comfyui.v1", job, "creative-1", creativeDigest, "project",
            profile, 2000, [new ProductionTaskPlanRecord("00000000-0000-0000-0000-000000000001", "shot", 1, "TEXT_CARD", "Executable",
                "text-card.v1", "text card", "fixed", 1, dimensions.Item1, dimensions.Item2, 24, 49, 2000, null)]);
        var productionPlanDigest = DigestJson(plan);
        var jobHash = Sha(job);
        var finalName = $"final-{jobHash[..32]}.mp4";
        var finalPath = Path.Combine(finals, finalName);
        if (real) await RealMedia.GenerateAsync(finalPath, dimensions.Item1, dimensions.Item2);
        else await File.WriteAllBytesAsync(finalPath, Encoding.ASCII.GetBytes("c004-video"));
        var finalSha = await ShaFileAsync(finalPath);
        var finalManifestPath = Path.Combine(finals, $"final-{jobHash[..32]}.final-video.json");
        await WriteJsonAsync(finalManifestPath, new
        {
            schema_version = "1.0", production_job_id = job, production_package_id = package,
            production_package_digest = packageDigest, source_output_sha256 = new[] { Sha("source") },
            final_file_name = finalName, final_sha256 = finalSha,
            final_bytes = new FileInfo(finalPath).Length, created_at = DateTimeOffset.UtcNow,
        });
        var c004 = new FinalVideoArtifact(job, package, packageDigest, finalPath, finalManifestPath,
            finalSha, new FileInfo(finalPath).Length, false);

        var narrationPlan = new NarrationPlanRecord("1.0", job, "creative-1", creativeDigest,
            productionPlanDigest, 2_000, NarrationPlanContract.TtsProfileId,
            NarrationPlanContract.VoiceProfileId, narrationRequired,
            narrationRequired
                ? [new NarrationSegmentPlanRecord("segment-1", "beat-1", 1, NarrationText,
                    Sha(NarrationText), 0, narrationWindowMs)]
                : []);
        var narrationResponse = new NarrationPlanResponseRecord(
            narrationPlan, NarrationPlanContract.ComputeDigest(narrationPlan));

        NarrationArtifact? narrationArtifact = null;
        if (narrationRequired)
        {
            var jobDir = Path.Combine(narration, $"{job}-{jobHash[..16]}");
            Directory.CreateDirectory(jobDir);
            var segment = narrationPlan.Segments[0];
            var wavName = $"001-segment-1-{segment.TextSha256}.wav";
            var wavPath = Path.Combine(jobDir, wavName);
            await File.WriteAllBytesAsync(wavPath, Wav(48_000, 1, wavFrames));
            var wavSha = await ShaFileAsync(wavPath);
            var manifestPath = Path.Combine(jobDir, "narration-manifest.json");
            await WriteJsonAsync(manifestPath, new
            {
                schema_version = "1.0", production_job_id = job, creative_package_id = "creative-1",
                creative_package_digest = creativeDigest, production_plan_digest = productionPlanDigest,
                narration_plan_digest = narrationResponse.NarrationPlanDigest,
                tts_profile_id = NarrationPlanContract.TtsProfileId,
                voice_profile_id = NarrationPlanContract.VoiceProfileId,
                resolved_voice_name = "fixture", resolved_voice_culture = "en-US",
                resolved_voice_identity_sha256 = Sha("voice"),
                segments = new[] { new {
                    segment_id = segment.SegmentId, beat_id = segment.BeatId, order = 1,
                    text_sha256 = segment.TextSha256, start_ms = 0L, end_ms = narrationWindowMs,
                    wav_file_name = wavName, wav_sha256 = wavSha, wav_bytes = new FileInfo(wavPath).Length,
                    wav_sample_rate = 48_000, wav_channels = 1, wav_bits = 16,
                    synthesized_duration_ms = wavFrames * 1_000L / 48_000,
                } }, created_at = DateTimeOffset.UtcNow,
            });
            narrationArtifact = new NarrationArtifact(manifestPath,
                [new NarrationArtifactSegment(wavName, wavPath)]);
        }

        var overlayCue = new CaptionOverlayCueRecord("cue-1", "beat-1", 1, "overlay", OverlayText,
            Sha(OverlayText), 0, 1_000);
        var overlayPlan = new CaptionOverlayPlanRecord("1.0", job, "creative-1", creativeDigest,
            productionPlanDigest, 2_000, profile, CaptionOverlayConstants.CaptionStyleProfileId,
            CaptionOverlayConstants.OverlayStyleProfileId, CaptionOverlayConstants.FontProfileId,
            false, overlaysRequired, [], overlaysRequired ? [overlayCue] : []);
        var overlayDigest = DigestJson(overlayPlan);
        var overlayResponse = new CaptionOverlayPlanResponseRecord(overlayPlan, overlayDigest);

        TextOverlayArtifact? overlayArtifact = null;
        if (overlaysRequired && real)
        {
            overlayArtifact = await new WindowsCaptionOverlayService(
                new WindowsCaptionOverlayRenderer(new TextOverlayProcessRunner()), new WindowsTextOverlayFontPolicy(),
                finals, overlays, TimeProvider.System).ApplyAsync(c004, overlayResponse, CancellationToken.None);
        }
        if (overlaysRequired && !real)
        {
            var overlayIdentity = OverlayIdentity(finalSha, overlayDigest, overlayPlan.OutputProfileId,
                overlayPlan.OverlayStyleProfileId, overlayPlan.FontProfileId, [Sha("font")]);
            var outputName = $"overlay-{overlayIdentity[..32]}.mp4";
            var outputPath = Path.Combine(overlays, outputName);
            if (real) File.Copy(finalPath, outputPath);
            else await File.WriteAllBytesAsync(outputPath, Encoding.ASCII.GetBytes("overlay-video"));
            var outputSha = await ShaFileAsync(outputPath);
            var manifestPath = Path.Combine(overlays, $"overlay-{overlayIdentity[..32]}.text-overlay.json");
            await WriteJsonAsync(manifestPath, new
            {
                schema_version = "1.0", production_job_id = job,
                source_production_package_id = package, source_production_package_digest = packageDigest,
                source_final_sha256 = finalSha, caption_overlay_plan_digest = overlayDigest,
                output_profile_id = overlayPlan.OutputProfileId,
                overlay_style_profile_id = CaptionOverlayConstants.OverlayStyleProfileId,
                font_profile_id = CaptionOverlayConstants.FontProfileId,
                renderer_profile_id = WindowsCaptionOverlayRenderer.RendererProfileId,
                artifact_identity_sha256 = overlayIdentity,
                cues = new[] { new { cue_id = "cue-1", beat_id = "beat-1", order = 1,
                    text_sha256 = overlayCue.TextSha256, start_ms = 0, end_ms = 1_000,
                    resolved_font_name = "arial.ttf", resolved_font_identity_sha256 = Sha("font") } },
                output_file_name = outputName, output_sha256 = outputSha,
                output_bytes = new FileInfo(outputPath).Length, passthrough = false,
                created_at = DateTimeOffset.UtcNow,
            });
            overlayArtifact = new TextOverlayArtifact(job, finalSha, overlayDigest,
                overlayPlan.OutputProfileId, outputPath, manifestPath, outputSha,
                new FileInfo(outputPath).Length, false, false);
        }

        var input = new MasterCompositionInputV1(c004, narrationResponse, narrationArtifact,
            overlayResponse, overlayArtifact);
        var composer = new FixtureComposer(real);
        var service = new PostProductionMasterCompositorService(composer, finals, narration, overlays,
            master, TimeProvider.System);
        return new Fixture(root, input, composer, service) { Plan = plan };
    }

    public void Dispose()
    {
        if (Directory.Exists(Root)) Directory.Delete(Root, recursive: true);
    }

    private static string DigestJson<T>(T value)
    {
        var node = JsonSerializer.SerializeToNode(value) ?? throw new InvalidOperationException();
        return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    }

    private static string OverlayIdentity(
        string sourceSha,
        string planDigest,
        string outputProfile,
        string overlayStyle,
        string fontProfile,
        IReadOnlyList<string> fontIdentities)
    {
        var fonts = new JsonArray();
        foreach (var identity in fontIdentities.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
        {
            fonts.Add(identity);
        }
        var node = new JsonObject
        {
            ["renderer_profile_id"] = WindowsCaptionOverlayRenderer.RendererProfileId,
            ["source_final_sha256"] = sourceSha,
            ["caption_overlay_plan_digest"] = planDigest,
            ["output_profile_id"] = outputProfile,
            ["overlay_style_profile_id"] = overlayStyle,
            ["font_profile_id"] = fontProfile,
            ["font_identity_sha256"] = fonts,
        };
        return Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(node))).ToLowerInvariant();
    }

    private static async Task WriteJsonAsync(string path, object value) =>
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(value), new UTF8Encoding(false));

    private static async Task<string> ShaFileAsync(string path) =>
        Convert.ToHexString(SHA256.HashData(await File.ReadAllBytesAsync(path))).ToLowerInvariant();

    private static byte[] Wav(int sampleRate, short channels, int frames)
    {
        var dataBytes = frames * channels * 2;
        var bytes = new byte[44 + dataBytes];
        "RIFF"u8.CopyTo(bytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), (uint)(bytes.Length - 8));
        "WAVEfmt "u8.CopyTo(bytes.AsSpan(8));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16), 16);
        BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(20), 1);
        BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(22), channels);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(24), sampleRate);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(28), sampleRate * channels * 2);
        BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(32), (short)(channels * 2));
        BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(34), 16);
        "data"u8.CopyTo(bytes.AsSpan(36));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(40), (uint)dataBytes);
        return bytes;
    }

    private static string Sha(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();

    public static string ShaValue(string value) => Sha(value);
}
