using System.Runtime.InteropServices.WindowsRuntime;
using Windows.Media.SpeechSynthesis;

namespace PicotooPet.Desktop.Services;

/// <summary>使用已验证的 OneCore 本地语音离线合成旁白，不接入云端或外部模型。</summary>
internal sealed class WindowsMediaSpeechBackend : INarrationSpeechBackend
{
    public IReadOnlyList<NarrationInstalledVoice> GetInstalledVoices() =>
        SpeechSynthesizer.AllVoices
            .Select(voice => new NarrationInstalledVoice(voice.Id, voice.DisplayName, voice.Language))
            .ToArray();

    public async Task<byte[]> SynthesizeAsync(
        NarrationInstalledVoice voice,
        string text,
        CancellationToken cancellationToken)
    {
        var installed = SpeechSynthesizer.AllVoices.SingleOrDefault(candidate =>
            string.Equals(candidate.Id, voice.Id, StringComparison.Ordinal));
        if (installed is null)
        {
            throw new NarrationSynthesisException("NARRATION_VOICE_UNAVAILABLE");
        }

        using var synthesizer = new SpeechSynthesizer { Voice = installed };
        using var stream = await synthesizer.SynthesizeTextToStreamAsync(text)
            .AsTask(cancellationToken).ConfigureAwait(false);
        using var source = stream.AsStreamForRead();
        using var destination = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true)
        {
            var read = await source.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }
            if (destination.Length + read > NarrationWavValidator.MaximumBytes)
            {
                throw new NarrationSynthesisException("NARRATION_WAV_INVALID");
            }
            await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken).ConfigureAwait(false);
        }
        return destination.ToArray();
    }
}
