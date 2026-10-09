using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMaster.SmokeTests;

internal static class Program
{
    private static async Task<int> Main()
    {
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("first compose and exact restart", FirstComposeAndExactRestartAsync),
            ("lineage fails before output root", LineageFailsBeforeOutputRootAsync),
            ("exact WAV window rejects one extra frame", ExactWavWindowRejectsOneExtraFrameAsync),
            ("tampered upstream bytes fail closed", TamperedUpstreamBytesFailClosedAsync),
            ("partial and tampered masters conflict", PartialAndTamperedMastersConflictAsync),
            ("stale wrong digest is never selected", StaleWrongDigestIsNeverSelectedAsync),
            ("identity ignores roots and timestamps", IdentityIgnoresRootsAndTimestampsAsync),
            ("identity changes with meaningful inputs", IdentityChangesWithMeaningfulInputsAsync),
            ("no postproduction returns C004 fallback", NoPostProductionReturnsFallbackAsync),
        };

        foreach (var test in tests)
        {
            await test.Run().ConfigureAwait(false);
            Console.WriteLine($"PASS {test.Name}");
        }
        Console.WriteLine("POSTPRODUCTION_MASTER_SMOKE=PASS");
        return 0;
    }

    private static async Task FirstComposeAndExactRestartAsync()
    {
        using var fixture = await Fixture.CreateAsync(narrationRequired: true, overlaysRequired: true);
        var first = await fixture.Service.ComposeAsync(fixture.Input);
        Assert(first.Required && first.Artifact is { Reused: false, HasAudio: true });
        Assert(fixture.Composer.Calls == 1);
        var second = await fixture.Service.ComposeAsync(fixture.Input);
        Assert(second.Artifact is { Reused: true });
        Assert(second.Artifact!.MasterInputDigest == first.Artifact!.MasterInputDigest);
        Assert(fixture.Composer.Calls == 1);
        var manifest = await File.ReadAllTextAsync(second.Artifact.ManifestPath);
        Assert(!manifest.Contains(Fixture.NarrationText, StringComparison.Ordinal));
        Assert(!manifest.Contains(Fixture.OverlayText, StringComparison.Ordinal));
        Assert(!manifest.Contains(fixture.Root, StringComparison.OrdinalIgnoreCase));
    }

    private static async Task LineageFailsBeforeOutputRootAsync()
    {
        using var fixture = await Fixture.CreateAsync(narrationRequired: false, overlaysRequired: true);
        fixture.Input = fixture.Input with
        {
            C004 = fixture.Input.C004 with { ProductionJobId = "wrong" },
        };
        await ThrowsAsync(MasterCompositionException.LineageMismatch,
            () => fixture.Service.ComposeAsync(fixture.Input));
        Assert(!Directory.Exists(fixture.MasterRoot));
        Assert(fixture.Composer.Calls == 0);
    }

    private static async Task ExactWavWindowRejectsOneExtraFrameAsync()
    {
        using var fixture = await Fixture.CreateAsync(narrationRequired: true, overlaysRequired: false,
            wavFrames: 48_001, narrationWindowMs: 1_000);
        await ThrowsAsync(MasterCompositionException.NarrationSegmentTooLong,
            () => fixture.Service.ComposeAsync(fixture.Input));
        Assert(fixture.Composer.Calls == 0);
    }

    private static async Task TamperedUpstreamBytesFailClosedAsync()
    {
        using var c004 = await Fixture.CreateAsync(false, false);
        await File.AppendAllTextAsync(c004.Input.C004.FilePath, "tamper");
        await ThrowsAsync(MasterCompositionException.VisualInvalid,
            () => c004.Service.ComposeAsync(c004.Input));

        using var overlay = await Fixture.CreateAsync(false, true);
        await File.AppendAllTextAsync(overlay.Input.OverlayArtifact!.FilePath, "tamper");
        await ThrowsAsync(MasterCompositionException.VisualInvalid,
            () => overlay.Service.ComposeAsync(overlay.Input));

        using var narration = await Fixture.CreateAsync(true, false);
        await File.AppendAllTextAsync(narration.Input.NarrationArtifact!.Segments[0].WavPath, "tamper");
        await ThrowsAsync(MasterCompositionException.NarrationInvalid,
            () => narration.Service.ComposeAsync(narration.Input));
    }

    private static async Task PartialAndTamperedMastersConflictAsync()
    {
        using var fixture = await Fixture.CreateAsync(true, false);
        var made = await fixture.Service.ComposeAsync(fixture.Input);
        var artifact = made.Artifact!;
        File.Delete(artifact.ManifestPath);
        await ThrowsAsync(MasterCompositionException.ArtifactConflict,
            () => fixture.Service.ComposeAsync(fixture.Input));

        using var manifestOnly = await Fixture.CreateAsync(true, false);
        var manifestOnlyMade = await manifestOnly.Service.ComposeAsync(manifestOnly.Input);
        File.Delete(manifestOnlyMade.Artifact!.FilePath);
        await ThrowsAsync(MasterCompositionException.ArtifactConflict,
            () => manifestOnly.Service.ComposeAsync(manifestOnly.Input));

        using var other = await Fixture.CreateAsync(true, false);
        var otherMade = await other.Service.ComposeAsync(other.Input);
        await File.AppendAllTextAsync(otherMade.Artifact!.FilePath, "tamper");
        await ThrowsAsync(MasterCompositionException.ArtifactConflict,
            () => other.Service.ComposeAsync(other.Input));
    }

    private static async Task StaleWrongDigestIsNeverSelectedAsync()
    {
        using var fixture = await Fixture.CreateAsync(true, false);
        var jobDirectory = Path.Combine(fixture.MasterRoot, $"job-1-{Fixture.ShaValue("job-1")[..16]}");
        var stale = Path.Combine(jobDirectory, new string('f', 64));
        Directory.CreateDirectory(stale);
        await File.WriteAllTextAsync(Path.Combine(stale, "master.mp4"), "stale");
        await File.WriteAllTextAsync(Path.Combine(stale, "master-manifest.json"), "stale");
        var result = await fixture.Service.ComposeAsync(fixture.Input);
        Assert(result.Artifact is { Reused: false });
        Assert(!result.Artifact!.FilePath.StartsWith(stale, StringComparison.OrdinalIgnoreCase));
    }

    private static async Task IdentityIgnoresRootsAndTimestampsAsync()
    {
        using var left = await Fixture.CreateAsync(true, true);
        using var right = await Fixture.CreateAsync(true, true);
        var a = await left.Service.ComposeAsync(left.Input);
        var b = await right.Service.ComposeAsync(right.Input);
        Assert(a.Artifact!.MasterInputDigest == b.Artifact!.MasterInputDigest);
    }

    private static async Task IdentityChangesWithMeaningfulInputsAsync()
    {
        using var left = await Fixture.CreateAsync(true, false, wavFrames: 24_000);
        using var right = await Fixture.CreateAsync(true, false, wavFrames: 24_001);
        var a = await left.Service.ComposeAsync(left.Input);
        var b = await right.Service.ComposeAsync(right.Input);
        Assert(a.Artifact!.MasterInputDigest != b.Artifact!.MasterInputDigest);
    }

    private static async Task NoPostProductionReturnsFallbackAsync()
    {
        using var fixture = await Fixture.CreateAsync(false, false);
        var result = await fixture.Service.ComposeAsync(fixture.Input);
        Assert(!result.Required && result.Artifact is null && result.C004Fallback is not null);
        Assert(fixture.Composer.Calls == 0);
        Assert(!Directory.Exists(fixture.MasterRoot));
    }

    private static async Task ThrowsAsync(string code, Func<Task> action)
    {
        try
        {
            await action().ConfigureAwait(false);
            throw new InvalidOperationException($"Expected {code}");
        }
        catch (MasterCompositionException exception) when (exception.Code == code)
        {
        }
    }

    private static void Assert(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Assertion failed.");
    }

    private sealed class FakeComposer : IMasterVideoComposer
    {
        public int Calls { get; private set; }

        public async Task ComposeAsync(MasterVideoCompositionRequest request, CancellationToken cancellationToken)
        {
            Calls++;
            var visual = await File.ReadAllBytesAsync(request.Visual.Path, cancellationToken);
            await File.WriteAllBytesAsync(request.OutputPath,
                visual.Concat(Encoding.ASCII.GetBytes($"|master|{request.NarrationSegments.Count}")).ToArray(),
                cancellationToken);
        }
    }

    private sealed class Fixture : IDisposable
    {
        public const string NarrationText = "private narration words";
        public const string OverlayText = "private overlay words";
        private Fixture(string root, MasterCompositionInputV1 input, FakeComposer composer,
            PostProductionMasterCompositorService service)
        {
            Root = root;
            Input = input;
            Composer = composer;
            Service = service;
        }

        public string Root { get; }
        public string MasterRoot => Path.Combine(Root, "master");
        public MasterCompositionInputV1 Input { get; set; }
        public FakeComposer Composer { get; }
        public PostProductionMasterCompositorService Service { get; }

        public static async Task<Fixture> CreateAsync(bool narrationRequired, bool overlaysRequired,
            int wavFrames = 24_000, long narrationWindowMs = 1_000)
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
            var productionPlanDigest = Sha("production-plan");
            var jobHash = Sha(job);
            var finalName = $"final-{jobHash[..32]}.mp4";
            var finalPath = Path.Combine(finals, finalName);
            await File.WriteAllBytesAsync(finalPath, Encoding.ASCII.GetBytes("c004-video"));
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
                productionPlanDigest, 2_000, "video.square.v1", CaptionOverlayConstants.CaptionStyleProfileId,
                CaptionOverlayConstants.OverlayStyleProfileId, CaptionOverlayConstants.FontProfileId,
                false, overlaysRequired, [], overlaysRequired ? [overlayCue] : []);
            var overlayDigest = DigestJson(overlayPlan);
            var overlayResponse = new CaptionOverlayPlanResponseRecord(overlayPlan, overlayDigest);

            TextOverlayArtifact? overlayArtifact = null;
            if (overlaysRequired)
            {
                var overlayIdentity = OverlayIdentity(finalSha, overlayDigest, overlayPlan.OutputProfileId,
                    overlayPlan.OverlayStyleProfileId, overlayPlan.FontProfileId, [Sha("font")]);
                var outputName = $"overlay-{overlayIdentity[..32]}.mp4";
                var outputPath = Path.Combine(overlays, outputName);
                await File.WriteAllBytesAsync(outputPath, Encoding.ASCII.GetBytes("overlay-video"));
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
            var composer = new FakeComposer();
            var service = new PostProductionMasterCompositorService(composer, finals, narration, overlays,
                master, TimeProvider.System);
            return new Fixture(root, input, composer, service);
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
}
