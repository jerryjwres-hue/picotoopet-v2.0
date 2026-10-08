using System.Security.Cryptography;

namespace PicotooPet.TextOverlayCompatibilityProbe;

internal sealed record FrameAnalysis(
    int FrameCount,
    int FirstInkFrame,
    int LastInkFrame,
    int InkFrames,
    BoundingBox? MidCueInkBox,
    string RawSha256);

/// <summary>Analyzes raw 8-bit gray frames cropped to the lower-third analysis region.</summary>
internal static class FrameAnalyzer
{
    private const int InkContrast = 60;
    private const int TextLuma = 160;

    public static FrameAnalysis Analyze(byte[] raw, int width, int regionHeight, int regionTop, int midFrame)
    {
        var frameSize = width * regionHeight;
        var frames = frameSize == 0 ? 0 : raw.Length / frameSize;
        var first = -1;
        var last = -1;
        var inkFrames = 0;
        BoundingBox? box = null;
        for (var frame = 0; frame < frames; frame++)
        {
            var span = raw.AsSpan(frame * frameSize, frameSize);
            byte min = 255;
            byte max = 0;
            foreach (var value in span)
            {
                min = value < min ? value : min;
                max = value > max ? value : max;
            }
            if (max - min < InkContrast)
            {
                continue;
            }
            inkFrames++;
            first = first < 0 ? frame : first;
            last = frame;
            if (frame == midFrame)
            {
                box = BoundingBoxOf(span, width, regionHeight, regionTop);
            }
        }
        return new FrameAnalysis(
            frames,
            first,
            last,
            inkFrames,
            box,
            Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant());
    }

    private static BoundingBox? BoundingBoxOf(ReadOnlySpan<byte> frame, int width, int height, int top)
    {
        int x0 = int.MaxValue, y0 = int.MaxValue, x1 = -1, y1 = -1;
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                if (frame[(y * width) + x] < TextLuma)
                {
                    continue;
                }
                x0 = Math.Min(x0, x);
                x1 = Math.Max(x1, x);
                y0 = Math.Min(y0, y);
                y1 = Math.Max(y1, y);
            }
        }
        return x1 < 0 ? null : new BoundingBox(x0, y0 + top, x1, y1 + top);
    }

    /// <summary>Synthetic frames for self-tests: ink (a bright rectangle) only on frames [from, to].</summary>
    public static byte[] BuildFixture(int frames, int width, int regionHeight, int from, int to)
    {
        var frameSize = width * regionHeight;
        var raw = new byte[frames * frameSize];
        Array.Fill(raw, (byte)40);
        for (var frame = from; frame <= to; frame++)
        {
            for (var y = 20; y < 40; y++)
            {
                for (var x = 100; x < 300; x++)
                {
                    raw[(frame * frameSize) + (y * width) + x] = 250;
                }
            }
        }
        return raw;
    }
}
