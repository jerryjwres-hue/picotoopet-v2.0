using System.Buffers.Binary;

namespace PicotooPet.TextOverlayCompatibilityProbe;

/// <summary>Minimal read-only cmap reader (TTF/OTF/TTC first face; formats 4 and 12) for glyph preflight.</summary>
internal static class SfntCmap
{
    public static bool TryCovers(ReadOnlySpan<byte> font, string text, out bool covers)
    {
        covers = false;
        if (!TryFindSubtable(font, out var subtable, out var format))
        {
            return false;
        }
        foreach (var rune in text.EnumerateRunes())
        {
            if (rune.Value == ' ')
            {
                continue;
            }
            if (!HasGlyph(font, subtable, format, rune.Value))
            {
                covers = false;
                return true;
            }
        }
        covers = true;
        return true;
    }

    private static bool TryFindSubtable(ReadOnlySpan<byte> font, out int subtable, out int format)
    {
        subtable = 0;
        format = 0;
        var faceOffset = 0;
        if (font.Length >= 16 && font[..4].SequenceEqual("ttcf"u8))
        {
            faceOffset = (int)BinaryPrimitives.ReadUInt32BigEndian(font.Slice(12, 4));
        }
        if (faceOffset < 0 || faceOffset + 12 > font.Length)
        {
            return false;
        }
        int tableCount = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(faceOffset + 4, 2));
        var cmapOffset = -1;
        for (var index = 0; index < tableCount; index++)
        {
            var record = faceOffset + 12 + (16 * index);
            if (record + 16 > font.Length)
            {
                return false;
            }
            if (font.Slice(record, 4).SequenceEqual("cmap"u8))
            {
                cmapOffset = (int)BinaryPrimitives.ReadUInt32BigEndian(font.Slice(record + 8, 4));
            }
        }
        if (cmapOffset < 0 || cmapOffset + 4 > font.Length)
        {
            return false;
        }

        int encodingCount = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(cmapOffset + 2, 2));
        var bestRank = -1;
        for (var index = 0; index < encodingCount; index++)
        {
            var record = cmapOffset + 4 + (8 * index);
            if (record + 8 > font.Length)
            {
                return false;
            }
            int platform = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(record, 2));
            int encoding = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(record + 2, 2));
            var offset = cmapOffset + (int)BinaryPrimitives.ReadUInt32BigEndian(font.Slice(record + 4, 4));
            var rank = (platform, encoding) switch
            {
                (3, 10) or (0, 4) or (0, 6) => 2, // full Unicode (format 12)
                (3, 1) or (0, 3) or (0, 0) or (0, 1) or (0, 2) => 1, // BMP (format 4)
                _ => -1,
            };
            if (rank > bestRank && offset + 4 <= font.Length)
            {
                var candidateFormat = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(offset, 2));
                if (candidateFormat is 4 or 12)
                {
                    bestRank = rank;
                    subtable = offset;
                    format = candidateFormat;
                }
            }
        }
        return bestRank >= 0;
    }

    private static bool HasGlyph(ReadOnlySpan<byte> font, int subtable, int format, int codePoint)
    {
        if (format == 12)
        {
            var groups = (int)BinaryPrimitives.ReadUInt32BigEndian(font.Slice(subtable + 12, 4));
            for (var index = 0; index < groups; index++)
            {
                var group = subtable + 16 + (12 * index);
                if (group + 12 > font.Length)
                {
                    return false;
                }
                var start = BinaryPrimitives.ReadUInt32BigEndian(font.Slice(group, 4));
                var end = BinaryPrimitives.ReadUInt32BigEndian(font.Slice(group + 4, 4));
                if (codePoint >= start && codePoint <= end)
                {
                    return true;
                }
            }
            return false;
        }

        if (codePoint > 0xFFFF)
        {
            return false;
        }
        int segmentX2 = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(subtable + 6, 2));
        var segments = segmentX2 / 2;
        var ends = subtable + 14;
        var starts = ends + segmentX2 + 2;
        var deltas = starts + segmentX2;
        var rangeOffsets = deltas + segmentX2;
        for (var index = 0; index < segments; index++)
        {
            int end = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(ends + (2 * index), 2));
            if (codePoint > end)
            {
                continue;
            }
            int start = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(starts + (2 * index), 2));
            if (codePoint < start)
            {
                return false;
            }
            int delta = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(deltas + (2 * index), 2));
            int rangeOffset = BinaryPrimitives.ReadUInt16BigEndian(font.Slice(rangeOffsets + (2 * index), 2));
            if (rangeOffset == 0)
            {
                return ((codePoint + delta) & 0xFFFF) != 0;
            }
            var glyphAddress = rangeOffsets + (2 * index) + rangeOffset + (2 * (codePoint - start));
            if (glyphAddress + 2 > font.Length)
            {
                return false;
            }
            return BinaryPrimitives.ReadUInt16BigEndian(font.Slice(glyphAddress, 2)) != 0;
        }
        return false;
    }

    /// <summary>Deterministic in-memory format-12 font fixture for self-tests.</summary>
    public static byte[] BuildFormat12Fixture(params (uint Start, uint End)[] ranges)
    {
        var subtableLength = 16 + (12 * ranges.Length);
        var bytes = new byte[12 + 16 + 12 + subtableLength];
        BinaryPrimitives.WriteUInt32BigEndian(bytes, 0x00010000);
        BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(4), 1);
        "cmap"u8.CopyTo(bytes.AsSpan(12));
        BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(20), 28);
        BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(24), (uint)(12 + subtableLength));
        // cmap header at 28: version 0, one encoding record (3,10) -> subtable at +12
        BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(30), 1);
        BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(32), 3);
        BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(34), 10);
        BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(36), 12);
        var subtable = 40;
        BinaryPrimitives.WriteUInt16BigEndian(bytes.AsSpan(subtable), 12);
        BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(subtable + 4), (uint)subtableLength);
        BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(subtable + 12), (uint)ranges.Length);
        for (var index = 0; index < ranges.Length; index++)
        {
            var group = subtable + 16 + (12 * index);
            BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(group), ranges[index].Start);
            BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(group + 4), ranges[index].End);
            BinaryPrimitives.WriteUInt32BigEndian(bytes.AsSpan(group + 8), 1);
        }
        return bytes;
    }
}
