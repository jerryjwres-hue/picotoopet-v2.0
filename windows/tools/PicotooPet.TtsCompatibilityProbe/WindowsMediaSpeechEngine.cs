using Windows.Media.SpeechSynthesis;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Candidate 2: Windows.Media.SpeechSynthesis (WinRT OneCore voices); in-process.</summary>
internal sealed class WindowsMediaSpeechEngine : ITtsEngine
{
    public string Name => "windows_media_speech";

    public string Dependency => "Windows SDK TFM net10.0-windows10.0.19041.0 (no package) + installed OneCore voices";

    public IReadOnlyList<VoiceInfo> EnumerateVoices() =>
        SpeechSynthesizer.AllVoices
            .Select(voice => new VoiceInfo(voice.Id, voice.DisplayName, voice.Language))
            .ToList();

    public async Task SynthesizeAsync(
        VoiceInfo voice,
        string text,
        string outputPath,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var synthesizer = new SpeechSynthesizer();
        synthesizer.Voice = SpeechSynthesizer.AllVoices.First(candidate => candidate.Id == voice.Id);

        using var stream = await synthesizer.SynthesizeTextToStreamAsync(text)
            .AsTask(cancellationToken)
            .ConfigureAwait(false);
        if (stream.Size is 0 or > (ulong)WavValidator.MaxBytes)
        {
            throw new InvalidDataException("synthesis stream size out of bounds");
        }

        using var input = stream.AsStreamForRead();
        await using var output = File.Create(outputPath);
        await input.CopyToAsync(output, cancellationToken).ConfigureAwait(false);
    }
}
