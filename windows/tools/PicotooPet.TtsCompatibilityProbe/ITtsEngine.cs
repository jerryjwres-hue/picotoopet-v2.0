namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Minimal engine seam: voices are chosen from the enumerated set, never from caller paths.</summary>
internal interface ITtsEngine
{
    string Name { get; }

    string Dependency { get; }

    IReadOnlyList<VoiceInfo> EnumerateVoices();

    /// <summary>Writes a PCM WAV to <paramref name="outputPath"/>; throws OperationCanceledException on cancel.</summary>
    Task SynthesizeAsync(VoiceInfo voice, string text, string outputPath, CancellationToken cancellationToken);
}
