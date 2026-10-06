using System.Buffers.Binary;

namespace PicotooPet.TtsCompatibilityProbe;

/// <summary>Validates a RIFF/WAVE PCM file header and bounded, nonzero data size.</summary>
internal static class WavValidator
{
    public const long MinBytes = 45;
    public const long MaxBytes = 16L * 1024 * 1024;

    public static bool TryValidate(ReadOnlySpan<byte> file, out WavInfo? info)
    {
        info = null;
        if (file.Length < MinBytes || file.Length > MaxBytes)
        {
            return false;
        }
        if (!file[..4].SequenceEqual("RIFF"u8) || !file.Slice(8, 4).SequenceEqual("WAVE"u8))
        {
            return false;
        }

        int format = 0, channels = 0, sampleRate = 0, bits = 0, byteRate = 0;
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
                sampleRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 4, 4));
                byteRate = (int)BinaryPrimitives.ReadUInt32LittleEndian(file.Slice(body + 8, 4));
                bits = BinaryPrimitives.ReadUInt16LittleEndian(file.Slice(body + 14, 2));
                haveFmt = true;
            }
            else if (id.SequenceEqual("data"u8))
            {
                if (!haveFmt)
                {
                    return false;
                }
                // Streaming writers may leave a placeholder size; clamp to the bytes actually present.
                var available = file.Length - body;
                var dataBytes = size > available ? available : size;
                if (format != 1 || channels is < 1 or > 2 || sampleRate is < 8000 or > 48000
                    || bits != 16 || byteRate <= 0 || dataBytes <= 0)
                {
                    return false;
                }
                info = new WavInfo(
                    format,
                    channels,
                    sampleRate,
                    bits,
                    dataBytes,
                    file.Length,
                    dataBytes * 1000 / byteRate);
                return true;
            }
            offset = (int)Math.Min(int.MaxValue, body + size + (size & 1));
        }
        return false;
    }

    /// <summary>Deterministic in-memory 16-bit mono PCM fixture for validator self-tests.</summary>
    public static byte[] BuildFixture(int dataBytes, bool corruptMagic = false)
    {
        var bytes = new byte[44 + dataBytes];
        "RIFF"u8.CopyTo(bytes);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(4), (uint)(36 + dataBytes));
        "WAVEfmt "u8.CopyTo(bytes.AsSpan(8));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(16), 16);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(20), 1);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(22), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(24), 22050);
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(28), 44100);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(32), 2);
        BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(34), 16);
        "data"u8.CopyTo(bytes.AsSpan(36));
        BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(40), (uint)dataBytes);
        if (corruptMagic)
        {
            bytes[0] = (byte)'X';
        }
        return bytes;
    }
}
