using System.Text.Json;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>
/// S003 compatibility probe. Accepts only a closed argument set; no voice/model/executable/URL input
/// exists. Writes only under a probe-managed temp directory that is always removed.
/// </summary>
internal static class Program
{
    private const int MinTimeoutSeconds = 1;
    private const int MaxTimeoutSeconds = 60;
    private const int DefaultTimeoutSeconds = 20;

    public static async Task<int> Main(string[] args)
    {
        if (!TryParse(args, out var engineFilter, out var timeoutSeconds, out var simulateNoVoice, out var selfTest))
        {
            Console.Error.WriteLine(
                "INVALID_ARGUMENT usage: [--engine system_speech|windows_media_speech|all] " +
                "[--timeout-seconds 1..60] [--simulate-no-voice] [--self-test]");
            return 3;
        }

        if (selfTest)
        {
            return SelfTest();
        }

        var workDirectory = Path.Combine(Path.GetTempPath(), "PicotooPetTtsProbe", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(workDirectory);
        try
        {
            var engines = new List<ITtsEngine>();
            if (engineFilter is "all" or "system_speech")
            {
                engines.Add(new SystemSpeechEngine());
            }
            if (engineFilter is "all" or "windows_media_speech")
            {
                engines.Add(new WindowsMediaSpeechEngine());
            }

            var reports = new List<EngineReport>();
            foreach (var engine in engines)
            {
                reports.Add(await ProbeRunner.RunAsync(
                    engine,
                    workDirectory,
                    TimeSpan.FromSeconds(timeoutSeconds),
                    simulateNoVoice).ConfigureAwait(false));
            }

            var report = new ProbeReport(
                "picotoopet.tts_compatibility.s003",
                ProbeRunner.Phrase,
                Environment.OSVersion.VersionString,
                System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                timeoutSeconds,
                simulateNoVoice,
                reports);
            Console.WriteLine(JsonSerializer.Serialize(report, ProbeJson.Options));
            return reports.Any(item => item.Status == StatusCodes.Pass) ? 0 : 1;
        }
        finally
        {
            try
            {
                Directory.Delete(workDirectory, recursive: true);
            }
            catch (IOException)
            {
                // Best-effort cleanup of the probe-managed directory only.
            }
        }
    }

    private static int SelfTest()
    {
        var good = WavValidator.TryValidate(WavValidator.BuildFixture(4410), out var info)
            && info is { SampleRate: 22050, Channels: 1, BitsPerSample: 16, DataBytes: 4410 };
        var badMagic = !WavValidator.TryValidate(WavValidator.BuildFixture(4410, corruptMagic: true), out _);
        var empty = !WavValidator.TryValidate(WavValidator.BuildFixture(0), out _);
        var truncated = !WavValidator.TryValidate(WavValidator.BuildFixture(4410).AsSpan(0, 30), out _);
        var picks = VoiceSelection.Select(
        [
            new VoiceInfo("z", "Zed", "zh-CN"),
            new VoiceInfo("b", "Beta", "en-GB"),
            new VoiceInfo("a", "Alpha", "en-US"),
        ]);
        var deterministic = picks?.Id == "a" && VoiceSelection.Select([new VoiceInfo("z", "Zed", "zh-CN")]) is null;

        var ok = good && badMagic && empty && truncated && deterministic;
        Console.WriteLine(JsonSerializer.Serialize(
            new
            {
                probe = "picotoopet.tts_compatibility.s003.self_test",
                wav_accepts_valid = good,
                wav_rejects_bad_magic = badMagic,
                wav_rejects_empty_data = empty,
                wav_rejects_truncated = truncated,
                voice_selection_deterministic = deterministic,
                status = ok ? StatusCodes.Pass : "FAIL",
            },
            ProbeJson.Options));
        return ok ? 0 : 1;
    }

    private static bool TryParse(
        string[] args,
        out string engine,
        out int timeoutSeconds,
        out bool simulateNoVoice,
        out bool selfTest)
    {
        engine = "all";
        timeoutSeconds = DefaultTimeoutSeconds;
        simulateNoVoice = false;
        selfTest = false;
        for (var index = 0; index < args.Length; index++)
        {
            switch (args[index])
            {
                case "--engine" when index + 1 < args.Length:
                    engine = args[++index];
                    if (engine is not ("all" or "system_speech" or "windows_media_speech"))
                    {
                        return false;
                    }
                    break;
                case "--timeout-seconds" when index + 1 < args.Length:
                    if (!int.TryParse(args[++index], out timeoutSeconds)
                        || timeoutSeconds is < MinTimeoutSeconds or > MaxTimeoutSeconds)
                    {
                        return false;
                    }
                    break;
                case "--simulate-no-voice":
                    simulateNoVoice = true;
                    break;
                case "--self-test":
                    selfTest = true;
                    break;
                default:
                    return false;
            }
        }
        return true;
    }
}
