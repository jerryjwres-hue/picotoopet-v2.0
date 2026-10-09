using System.Buffers.Binary;

namespace PicotooPet.PostProductionAudioMuxProbe;

internal sealed record WavFacts(int Channels, int SampleRate, int BitsPerSample, long DataBytes, long DurationMs);

/// <summary>Synthetic PCM16 WAV writer and bounded header parser (no external runtime).</summary>
internal static class WavFile
{
    public const long MaxBytes = 64L * 1024 * 1024;

    public static byte[] Build(int sampleRate, int channels, int durationMs, double frequencyHz, double amplitude = 0.5)
    {
        var frames = (int)((long)sampleRate * durationMs / 1000);
        var dataBytes = frames * channels * 2;
        var bytes = new byte[44 + dataBytes];
        "RIFF"u8.CopyTo(bytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), (uint)(36 + dataBytes));
        "WAVEfmt "u8.CopyTo(bytes.AsSpan(8));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16), 16);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(20), 1);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(22), (ushort)channels);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(24), (uint)sampleRate);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(28), (uint)(sampleRate * channels * 2));
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(32), (ushort)(channels * 2));
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(34), 16);
        "data"u8.CopyTo(bytes.AsSpan(36));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(40), (uint)dataBytes);
        var offset = 44;
        for (var frame = 0; frame < frames; frame++)
        {
            var sample = (short)(amplitude * short.MaxValue * Math.Sin(2 * Math.PI * frequencyHz * frame / sampleRate));
            for (var channel = 0; channel < channels; channel++)
            {
                BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(offset), sample);
                offset += 2;
            }
        }
        return bytes;
    }

    /// <summary>Accepts only canonical PCM16 RIFF/WAVE (1–2 channels, 8–96 kHz) with a positive data chunk.</summary>
    public static bool TryParse(ReadOnlySpan<byte> file, out WavFacts? facts)
    {
        facts = null;
        if (file.Length < 45 || file.Length > MaxBytes
            || !file[..4].SequenceEqual("RIFF"u8) || !file.Slice(8, 4).SequenceEqual("WAVE"u8))
        {
            return false;
        }
        int format = 0, channels = 0, rate = 0, bits = 0;
        var haveFmt = false;
        var offset = 12;
        while (offset + 8 <= file.Length)
        {
            var id = file.Slice(offset, 4);
            var size = (long)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(offset + 4, 4));
            var body = offset + 8;
            if (id.SequenceEqual("fmt "u8))
            {
                if (size < 16 || body + 16 > file.Length)
                {
                    return false;
                }
                format = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body, 2));
                channels = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 2, 2));
                rate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 4, 4));
                bits = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 14, 2));
                haveFmt = true;
            }
            else if (id.SequenceEqual("data"u8))
            {
                var available = file.Length - body;
                var dataBytes = size > available ? available : size;
                if (!haveFmt || format != 1 || bits != 16 || channels is < 1 or > 2
                    || rate is < 8000 or > 96000 || dataBytes <= 0)
                {
                    return false;
                }
                facts = new WavFacts(channels, rate, bits, dataBytes, dataBytes * 1000 / ((long)rate * channels * 2));
                return true;
            }
            offset = (int)Math.Min(int.MaxValue, body + size + (size & 1));
        }
        return false;
    }
}
