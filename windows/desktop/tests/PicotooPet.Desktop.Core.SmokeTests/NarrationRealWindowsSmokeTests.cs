using System.Security.Cryptography;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class NarrationRealWindowsSmokeTests
{
    public static async Task RunAsync()
    {
        var backend = new CountingBackend(new WindowsMediaSpeechBackend());
        var voices = backend.GetInstalledVoices();
        SmokeAssert.True(voices.Count > 0, "No OneCore voice is installed");
        var root = Path.Combine(Path.GetTempPath(), $"picotoopet-narration-real-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            if (voices.Any(voice => voice.Culture.StartsWith("en", StringComparison.OrdinalIgnoreCase)))
            {
                await VerifyPlanAsync(root, backend, "real-en", ["Hello from PicotooPet.", "This is the second segment."])
                    .ConfigureAwait(false);
            }
            if (voices.Any(voice => voice.Culture.StartsWith("zh", StringComparison.OrdinalIgnoreCase)))
            {
                await VerifyPlanAsync(root, backend, "real-zh", ["你好，欢迎使用。", "这是第二段旁白。"])
                    .ConfigureAwait(false);
            }
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task VerifyPlanAsync(
        string root,
        CountingBackend backend,
        string jobId,
        string[] text)
    {
        var segments = text.Select((value, index) => new NarrationSegmentPlanRecord(
            $"segment-{index + 1}", $"beat-{index + 1}", index + 1, value, Sha(value),
            index * 10_000, (index + 1) * 10_000)).ToArray();
        var response = new NarrationPlanResponseRecord(
            new NarrationPlanRecord("1.0", jobId, "creative-real", Sha("creative-real"),
                Sha("production-real"), 20_000, NarrationPlanContract.TtsProfileId,
                NarrationPlanContract.VoiceProfileId, true, segments),
            Sha(jobId));
        var service = new WindowsNarrationSynthesisService(root, backend, TimeSpan.FromSeconds(30));
        var before = backend.SynthesisCount;
        var first = await service.SynthesizeAsync(response, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.True(first.Segments.All(segment => File.Exists(segment.WavPath)), "Real managed WAV missing");
        _ = await service.SynthesizeAsync(response, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(before + segments.Length, backend.SynthesisCount, "Real artifact did not restart-reuse");
    }

    private static string Sha(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();

    private sealed class CountingBackend(INarrationSpeechBackend inner) : INarrationSpeechBackend
    {
        public int SynthesisCount { get; private set; }
        public IReadOnlyList<NarrationInstalledVoice> GetInstalledVoices() => inner.GetInstalledVoices();
        public async Task<byte[]> SynthesizeAsync(
            NarrationInstalledVoice voice,
            string text,
            CancellationToken cancellationToken)
        {
            SynthesisCount++;
            return await inner.SynthesizeAsync(voice, text, cancellationToken).ConfigureAwait(false);
        }
    }
}
