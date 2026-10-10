using System.Buffers.Binary;
using System.Security.Cryptography;
using PicotooPet.Desktop.Services;

namespace PicotooPet.PostProductionMasterMux.SmokeTests;

/// <summary>合成 PCM16 WAV（L=R 立体声）、C009A 风格的已验证片段，以及信号分析。</summary>
internal static class TestMedia
{
    public static byte[] Wav(int sampleRate, int channels, long frames, double hz, double amplitude = 0.5)
    {
        var dataBytes = checked((int)(frames * channels * 2));
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
        for (long frame = 0; frame < frames; frame++)
        {
            var sample = (short)(amplitude * short.MaxValue * Math.Sin(2 * Math.PI * hz * frame / sampleRate));
            for (var channel = 0; channel < channels; channel++)
            {
                BinaryPrimitives.WriteInt16LittleEndian(bytes.AsSpan(offset), sample);
                offset += 2;
            }
        }
        return bytes;
    }

    public static string Sha(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    /// <summary>写入 WAV 并返回与 C009A 产出形状一致的已验证片段。</summary>
    public static VerifiedMasterNarrationSegment Segment(
        string directory, int order, int rate, int channels, long frames, long startMs, long endMs, double hz)
    {
        var bytes = Wav(rate, channels, frames, hz);
        var path = Path.Combine(directory, $"seg{order}.wav");
        File.WriteAllBytes(path, bytes);
        return new VerifiedMasterNarrationSegment(
            $"seg-{order}", order, path, Sha(bytes), bytes.LongLength, startMs, endMs,
            frames * 1000 / rate, frames, rate, (short)channels);
    }

    public static double Rms(ReadOnlySpan<byte> pcm, int fromMs, int toMs)
    {
        var total = pcm.Length / 2;
        var start = Math.Clamp(fromMs * 48, 0, total);
        var end = Math.Clamp(toMs * 48, start, total);
        if (end == start)
        {
            return 0;
        }
        double sum = 0;
        for (var index = start; index < end; index++)
        {
            double sample = BitConverter.ToInt16(pcm.Slice(index * 2, 2));
            sum += sample * sample;
        }
        return Math.Sqrt(sum / (end - start));
    }

    public static int StrongestTone(ReadOnlySpan<byte> pcm, int fromMs, int toMs, params int[] candidates)
    {
        var total = pcm.Length / 2;
        var start = Math.Clamp(fromMs * 48, 0, total);
        var end = Math.Clamp(toMs * 48, start, total);
        var best = 0;
        double bestMagnitude = 0;
        foreach (var hz in candidates)
        {
            var coefficient = 2 * Math.Cos(2 * Math.PI * hz / 48000);
            double q1 = 0, q2 = 0;
            for (var index = start; index < end; index++)
            {
                var q0 = BitConverter.ToInt16(pcm.Slice(index * 2, 2)) + (coefficient * q1) - q2;
                q2 = q1;
                q1 = q0;
            }
            var magnitude = Math.Sqrt((q1 * q1) + (q2 * q2) - (coefficient * q1 * q2)) / Math.Max(1, end - start);
            if (magnitude > bestMagnitude)
            {
                bestMagnitude = magnitude;
                best = hz;
            }
        }
        return bestMagnitude > 100 ? best : 0;
    }

    public static short PeakAbs(ReadOnlySpan<byte> pcm)
    {
        var peak = 0;
        for (var index = 0; index + 1 < pcm.Length; index += 2)
        {
            peak = Math.Max(peak, Math.Abs((int)BitConverter.ToInt16(pcm.Slice(index, 2))));
        }
        return (short)Math.Min(peak, short.MaxValue);
    }
}
