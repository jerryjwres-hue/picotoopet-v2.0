using System.Speech.AudioFormat;
using System.Speech.Synthesis;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Candidate 1: System.Speech (SAPI 5) in-process; no shell-out, no network.</summary>
internal sealed class SystemSpeechEngine : ITtsEngine
{
    public string Name => "system_speech";

    public string Dependency => "NuGet System.Speech (probe-scoped) + installed SAPI5 voices";

    public IReadOnlyList<VoiceInfo> EnumerateVoices()
    {
        using var synthesizer = new SpeechSynthesizer();
        return synthesizer.GetInstalledVoices()
            .Where(voice => voice.Enabled)
            .Select(voice => new VoiceInfo(
                voice.VoiceInfo.Name,
                voice.VoiceInfo.Name,
                voice.VoiceInfo.Culture.Name))
            .ToList();
    }

    public async Task SynthesizeAsync(
        VoiceInfo voice,
        string text,
        string outputPath,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var synthesizer = new SpeechSynthesizer();
        synthesizer.SelectVoice(voice.Id);
        synthesizer.SetOutputToWaveFile(
            outputPath,
            new SpeechAudioFormatInfo(22050, AudioBitsPerSample.Sixteen, AudioChannel.Mono));

        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        synthesizer.SpeakCompleted += (_, args) =>
        {
            if (args.Cancelled)
            {
                completion.TrySetCanceled();
            }
            else if (args.Error is not null)
            {
                completion.TrySetException(args.Error);
            }
            else
            {
                completion.TrySetResult();
            }
        };

        synthesizer.SpeakAsync(text);
        using var registration = cancellationToken.Register(() => synthesizer.SpeakAsyncCancelAll());
        try
        {
            await completion.Task.ConfigureAwait(false);
        }
        finally
        {
            // Closing the output flushes the WAV header before the synthesizer is disposed.
            synthesizer.SetOutputToNull();
        }
    }
}
