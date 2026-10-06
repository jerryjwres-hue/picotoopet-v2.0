using System.Diagnostics;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Runs one engine through enumerate → select → synthesize → validate → cancel checks.</summary>
internal static class ProbeRunner
{
    public const string Phrase = "PicotooPet narration compatibility check.";
    private const string LongPhraseSeparator = " ";
    private const int LongPhraseRepeats = 40;
    private const int CancelAfterMs = 150;
    private const int CancelBoundMs = 5000;
    private static readonly TimeSpan UnresponsiveGrace = TimeSpan.FromSeconds(5);

    public static async Task<EngineReport> RunAsync(
        ITtsEngine engine,
        string workDirectory,
        TimeSpan timeout,
        bool simulateNoVoice)
    {
        IReadOnlyList<VoiceInfo> voices;
        try
        {
            voices = simulateNoVoice ? Array.Empty<VoiceInfo>() : engine.EnumerateVoices();
        }
        catch (Exception)
        {
            return Report(engine, StatusCodes.EngineUnavailable, [], null, null, 0, null);
        }

        var selected = VoiceSelection.Select(voices);
        if (selected is null)
        {
            return Report(engine, StatusCodes.NoCompatibleVoice, voices, null, null, 0, null);
        }

        var outputPath = Path.Combine(workDirectory, $"{engine.Name}.wav");
        var clock = Stopwatch.StartNew();
        var status = await SynthesizeBoundedAsync(engine, selected, Phrase, outputPath, timeout)
            .ConfigureAwait(false);
        var elapsed = clock.ElapsedMilliseconds;

        WavInfo? wav = null;
        if (status == StatusCodes.Pass)
        {
            var bytes = File.Exists(outputPath) ? await File.ReadAllBytesAsync(outputPath).ConfigureAwait(false)
                : Array.Empty<byte>();
            if (!WavValidator.TryValidate(bytes, out wav))
            {
                status = StatusCodes.InvalidWav;
            }
        }

        var cancellation = await RunCancellationCheckAsync(engine, selected, workDirectory).ConfigureAwait(false);
        return Report(engine, status, voices, selected, wav, elapsed, cancellation);
    }

    private static async Task<string> SynthesizeBoundedAsync(
        ITtsEngine engine,
        VoiceInfo voice,
        string text,
        string outputPath,
        TimeSpan timeout)
    {
        using var cancellation = new CancellationTokenSource(timeout);
        try
        {
            // Hard outer bound: even a synthesizer that ignores cancellation cannot hang the probe.
            await engine.SynthesizeAsync(voice, text, outputPath, cancellation.Token)
                .WaitAsync(timeout + UnresponsiveGrace)
                .ConfigureAwait(false);
            return StatusCodes.Pass;
        }
        catch (TimeoutException)
        {
            return StatusCodes.Unresponsive;
        }
        catch (OperationCanceledException)
        {
            return cancellation.IsCancellationRequested ? StatusCodes.Timeout : StatusCodes.Cancelled;
        }
        catch (Exception)
        {
            return StatusCodes.SynthesisFailed;
        }
    }

    private static async Task<CancellationReport> RunCancellationCheckAsync(
        ITtsEngine engine,
        VoiceInfo voice,
        string workDirectory)
    {
        // Fixed long phrase (repeats of the fixed safe phrase) guarantees cancel lands mid-synthesis.
        var longText = string.Join(LongPhraseSeparator, Enumerable.Repeat(Phrase, LongPhraseRepeats));
        var path = Path.Combine(workDirectory, $"{engine.Name}.cancel.wav");
        using var cancellation = new CancellationTokenSource();
        var clock = Stopwatch.StartNew();
        cancellation.CancelAfter(CancelAfterMs);
        string status;
        try
        {
            await engine.SynthesizeAsync(voice, longText, path, cancellation.Token)
                .WaitAsync(TimeSpan.FromMilliseconds(CancelBoundMs))
                .ConfigureAwait(false);
            status = StatusCodes.NotRun; // finished before cancel landed; cancel not demonstrated
        }
        catch (TimeoutException)
        {
            status = StatusCodes.Unresponsive;
        }
        catch (OperationCanceledException)
        {
            status = StatusCodes.Cancelled;
        }
        catch (Exception)
        {
            status = StatusCodes.SynthesisFailed;
        }
        var elapsed = clock.ElapsedMilliseconds;
        return new CancellationReport(status, elapsed, status == StatusCodes.Cancelled && elapsed <= CancelBoundMs);
    }

    private static EngineReport Report(
        ITtsEngine engine,
        string status,
        IReadOnlyList<VoiceInfo> voices,
        VoiceInfo? selected,
        WavInfo? wav,
        long elapsedMs,
        CancellationReport? cancellation) =>
        new(engine.Name, engine.Dependency, status, voices, selected, true, wav, elapsedMs, cancellation);
}
