using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class NarrationSynthesisSmokeTests
{
    private const string EnglishVoiceId = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\en-test";
    private const string ChineseVoiceId = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\zh-test";

    public static async Task RunAsync()
    {
        VerifyVoiceSelection();
        VerifyWavValidation();
        await VerifyArtifactAndReuseAsync().ConfigureAwait(false);
        await VerifyConflictsAsync().ConfigureAwait(false);
        await VerifyTimeoutAndCancellationAsync().ConfigureAwait(false);
        await VerifyEmptyPlanAsync().ConfigureAwait(false);
    }

    private static void VerifyVoiceSelection()
    {
        var voices = new[]
        {
            new NarrationInstalledVoice("z", "Zeta", "en-US"),
            new NarrationInstalledVoice("b", "Alpha", "en-GB"),
            new NarrationInstalledVoice("a", "Alpha", "en-US"),
            new NarrationInstalledVoice(ChineseVoiceId, "Chinese", "zh-CN"),
        };
        var english = NarrationVoiceSelector.Select(voices, [Segment("Hello.", 1, 0, 2_000)]);
        SmokeAssert.Equal("a", english.Id, "English selection was not exact-culture/name/id deterministic");
        var chinese = NarrationVoiceSelector.Select(voices, [Segment("你好 world", 1, 0, 2_000)]);
        SmokeAssert.Equal(ChineseVoiceId, chinese.Id, "Han text did not choose the zh-CN family");
        var supplementaryHan = NarrationVoiceSelector.Select(voices, [Segment("𠀀", 1, 0, 2_000)]);
        SmokeAssert.Equal(ChineseVoiceId, supplementaryHan.Id, "Supplementary CJK ideograph did not choose zh-CN");

        try
        {
            _ = NarrationVoiceSelector.Select(
                [new NarrationInstalledVoice("fr", "French", "fr-FR")],
                [Segment("Hello.", 1, 0, 2_000)]);
            throw new InvalidOperationException("Missing compatible voice did not fail");
        }
        catch (NarrationSynthesisException exception)
        {
            SmokeAssert.Equal("NARRATION_VOICE_UNAVAILABLE", exception.Message, "Wrong voice failure code");
        }
    }

    private static void VerifyWavValidation()
    {
        var valid = Wav(16_000, 1, 16, 400);
        var facts = NarrationWavValidator.Validate(valid);
        SmokeAssert.Equal(400L, facts.DurationMs, "PCM duration was not derived from the WAV header");
        foreach (var invalid in new[] { Array.Empty<byte>(), valid[..20], Encoding.ASCII.GetBytes("not a wav") })
        {
            try
            {
                _ = NarrationWavValidator.Validate(invalid);
                throw new InvalidOperationException("Invalid WAV was accepted");
            }
            catch (NarrationSynthesisException exception)
            {
                SmokeAssert.Equal("NARRATION_WAV_INVALID", exception.Message, "Wrong invalid WAV code");
            }
        }
    }

    private static async Task VerifyArtifactAndReuseAsync()
    {
        var root = TempRoot();
        try
        {
            var backend = new FakeBackend(
                [new NarrationInstalledVoice(EnglishVoiceId, "English Voice", "en-US")],
                Wav(16_000, 1, 16, 350));
            var service = new WindowsNarrationSynthesisService(root, backend, TimeSpan.FromSeconds(2));
            var plan = Response("job/one", "1", [Segment("Hello.", 1, 0, 1_000), Segment("World.", 2, 1_000, 2_000)]);
            var first = await service.SynthesizeAsync(plan, CancellationToken.None).ConfigureAwait(false);
            var second = await service.SynthesizeAsync(plan, CancellationToken.None).ConfigureAwait(false);

            SmokeAssert.Equal(2, backend.SynthesisCount, "Verified artifact was not reused without synthesis");
            SmokeAssert.Equal(first.ManifestPath, second.ManifestPath, "Reuse returned a different artifact");
            SmokeAssert.Equal(1, backend.VoiceIds.Distinct(StringComparer.Ordinal).Count(),
                "One selected voice was not used for the full plan");
            SmokeAssert.True(first.Segments.All(item => File.Exists(item.WavPath)), "Managed WAV was not promoted");
            var manifest = await File.ReadAllTextAsync(first.ManifestPath).ConfigureAwait(false);
            SmokeAssert.True(!manifest.Contains("Hello.", StringComparison.Ordinal), "Narration text leaked into manifest");
            SmokeAssert.True(!manifest.Contains(EnglishVoiceId, StringComparison.Ordinal), "Raw voice id leaked into manifest");
            SmokeAssert.True(!manifest.Contains(root, StringComparison.OrdinalIgnoreCase), "Absolute path leaked into manifest");
            SmokeAssert.True(first.Segments[0].FileName.Contains(plan.Plan.Segments[0].TextSha256, StringComparison.Ordinal),
                "Segment filename was not bound to source text SHA");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task VerifyConflictsAsync()
    {
        var root = TempRoot();
        try
        {
            var backend = new FakeBackend(
                [new NarrationInstalledVoice(EnglishVoiceId, "English Voice", "en-US")],
                Wav(16_000, 1, 16, 300));
            var service = new WindowsNarrationSynthesisService(root, backend, TimeSpan.FromSeconds(2));
            var plan = Response("job-conflict", "1", [Segment("Hello.", 1, 0, 1_000)]);
            var artifact = await service.SynthesizeAsync(plan, CancellationToken.None).ConfigureAwait(false);
            await using (var stream = new FileStream(artifact.Segments[0].WavPath, FileMode.Append, FileAccess.Write, FileShare.None))
            {
                await stream.WriteAsync(new byte[] { 0x42 }).ConfigureAwait(false);
            }
            await ExpectCodeAsync("NARRATION_ARTIFACT_CONFLICT", () => service.SynthesizeAsync(plan, CancellationToken.None));

            var changedRoot = TempRoot();
            try
            {
                var changedService = new WindowsNarrationSynthesisService(changedRoot, backend, TimeSpan.FromSeconds(2));
                _ = await changedService.SynthesizeAsync(Response("changed", "1", [Segment("Hello.", 1, 0, 1_000)]), CancellationToken.None).ConfigureAwait(false);
                var changed = Response("changed", "2", [Segment("Changed text.", 1, 0, 1_000)]);
                await ExpectCodeAsync(
                    "NARRATION_ARTIFACT_CONFLICT",
                    () => changedService.SynthesizeAsync(changed, CancellationToken.None));
            }
            finally
            {
                Directory.Delete(changedRoot, recursive: true);
            }

            var partialRoot = TempRoot();
            try
            {
                var partialService = new WindowsNarrationSynthesisService(partialRoot, backend, TimeSpan.FromSeconds(2));
                var partial = await partialService.SynthesizeAsync(Response("partial", "1", [Segment("Hello.", 1, 0, 1_000)]), CancellationToken.None).ConfigureAwait(false);
                File.Delete(partial.ManifestPath);
                await ExpectCodeAsync("NARRATION_ARTIFACT_CONFLICT", () => partialService.SynthesizeAsync(Response("partial", "1", [Segment("Hello.", 1, 0, 1_000)]), CancellationToken.None));
            }
            finally
            {
                Directory.Delete(partialRoot, recursive: true);
            }
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task VerifyTimeoutAndCancellationAsync()
    {
        var root = TempRoot();
        try
        {
            var timeoutBackend = new FakeBackend(
                [new NarrationInstalledVoice(EnglishVoiceId, "English Voice", "en-US")], null);
            var service = new WindowsNarrationSynthesisService(root, timeoutBackend, TimeSpan.FromMilliseconds(30));
            await ExpectCodeAsync("NARRATION_TTS_TIMEOUT", () => service.SynthesizeAsync(
                Response("timeout", "1", [Segment("secret narration", 1, 0, 1_000)]), CancellationToken.None));
            SmokeAssert.True(!Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Any(),
                "Timeout promoted a durable partial");

            using var cancelled = new CancellationTokenSource();
            cancelled.Cancel();
            try
            {
                await service.SynthesizeAsync(
                    Response("cancelled", "1", [Segment("secret narration", 1, 0, 1_000)]), cancelled.Token)
                    .ConfigureAwait(false);
                throw new InvalidOperationException("Cancelled synthesis completed");
            }
            catch (OperationCanceledException)
            {
                SmokeAssert.True(!Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Any(),
                    "Cancellation promoted a durable partial");
            }

            var tooLong = new WindowsNarrationSynthesisService(
                TempRoot(),
                new FakeBackend([new NarrationInstalledVoice(EnglishVoiceId, "English Voice", "en-US")], Wav(16_000, 1, 16, 1_300)),
                TimeSpan.FromSeconds(2));
            try
            {
                await ExpectCodeAsync("NARRATION_SEGMENT_TOO_LONG", () => tooLong.SynthesizeAsync(
                    Response("long", "1", [Segment("secret narration", 1, 0, 1_000)]), CancellationToken.None));
            }
            finally
            {
                Directory.Delete(tooLong.ManagedRoot, recursive: true);
            }
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task VerifyEmptyPlanAsync()
    {
        var root = TempRoot();
        try
        {
            var backend = new FakeBackend([], Wav(16_000, 1, 16, 100));
            var artifact = await new WindowsNarrationSynthesisService(root, backend, TimeSpan.FromSeconds(2))
                .SynthesizeAsync(Response("empty", "1", []), CancellationToken.None).ConfigureAwait(false);
            SmokeAssert.Equal(0, backend.SynthesisCount, "Empty narration invoked the synthesizer");
            SmokeAssert.Equal(0, artifact.Segments.Count, "Empty narration produced segments");
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task ExpectCodeAsync(string code, Func<Task> action)
    {
        try
        {
            await action().ConfigureAwait(false);
            throw new InvalidOperationException($"Expected {code}");
        }
        catch (NarrationSynthesisException exception)
        {
            SmokeAssert.Equal(code, exception.Message, "Wrong bounded synthesis code");
            SmokeAssert.True(!exception.ToString().Contains("secret narration", StringComparison.Ordinal), "Narration text leaked in error");
        }
    }

    private static NarrationPlanResponseRecord Response(string jobId, string digestSeed, NarrationSegmentPlanRecord[] segments)
    {
        var record = new NarrationPlanRecord(
            "1.0", jobId, "creative-1", Sha("creative"), Sha("production"),
            segments.Length == 0 ? 1_000 : segments.Max(item => item.EndMs),
            NarrationPlanContract.TtsProfileId, NarrationPlanContract.VoiceProfileId,
            segments.Length > 0, segments);
        var response = new NarrationPlanResponseRecord(
            record,
            NarrationPlanContract.ComputeDigest(record));
        NarrationPlanContract.Validate(response);
        return response;
    }

    private static NarrationSegmentPlanRecord Segment(string text, int order, long start, long end) =>
        new($"segment-{order}", $"beat-{order}", order, text, Sha(text), start, end);

    private static string Sha(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();

    internal static byte[] Wav(int sampleRate, short channels, short bits, int durationMs)
    {
        var dataBytes = sampleRate * channels * (bits / 8) * durationMs / 1_000;
        var bytes = new byte[44 + dataBytes];
        Encoding.ASCII.GetBytes("RIFF").CopyTo(bytes, 0);
        BitConverter.GetBytes(bytes.Length - 8).CopyTo(bytes, 4);
        Encoding.ASCII.GetBytes("WAVEfmt ").CopyTo(bytes, 8);
        BitConverter.GetBytes(16).CopyTo(bytes, 16);
        BitConverter.GetBytes((short)1).CopyTo(bytes, 20);
        BitConverter.GetBytes(channels).CopyTo(bytes, 22);
        BitConverter.GetBytes(sampleRate).CopyTo(bytes, 24);
        BitConverter.GetBytes(sampleRate * channels * (bits / 8)).CopyTo(bytes, 28);
        BitConverter.GetBytes((short)(channels * (bits / 8))).CopyTo(bytes, 32);
        BitConverter.GetBytes(bits).CopyTo(bytes, 34);
        Encoding.ASCII.GetBytes("data").CopyTo(bytes, 36);
        BitConverter.GetBytes(dataBytes).CopyTo(bytes, 40);
        return bytes;
    }

    private static string TempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), $"picotoopet-narration-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private sealed class FakeBackend(IReadOnlyList<NarrationInstalledVoice> voices, byte[]? wav) : INarrationSpeechBackend
    {
        public int SynthesisCount { get; private set; }
        public List<string> VoiceIds { get; } = [];
        public IReadOnlyList<NarrationInstalledVoice> GetInstalledVoices() => voices;

        public async Task<byte[]> SynthesizeAsync(NarrationInstalledVoice voice, string text, CancellationToken cancellationToken)
        {
            SynthesisCount++;
            VoiceIds.Add(voice.Id);
            if (wav is not null)
            {
                return wav;
            }
            await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken).ConfigureAwait(false);
            return [];
        }
    }
}
