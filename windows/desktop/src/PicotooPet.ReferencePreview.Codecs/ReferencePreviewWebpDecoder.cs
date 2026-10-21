using SkiaSharp;

namespace PicotooPet.ReferencePreview.Codecs;

/// <summary>Bounded CPU-only WebP pixels for WPF preview. No Mac Core, GPU or Comfy dependencies.</summary>
public static class ReferencePreviewWebpDecoder
{
    public sealed record DecodedImage(int Width, int Height, int Stride, byte[] Pixels);

    public static DecodedImage Decode(byte[] bytes, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(bytes);
        cancellationToken.ThrowIfCancellationRequested();
        if (bytes.Length is <= 0 or > 32 * 1024 * 1024)
            throw new InvalidDataException("REFERENCE_IMAGE_SIZE_INVALID");
        using var data = SKData.CreateCopy(bytes);
        using var decoder = SKCodec.Create(data);
        if (decoder is null || decoder.EncodedFormat != SKEncodedImageFormat.Webp || decoder.FrameCount > 1
            || decoder.Info.Width is <= 0 or > 8192 || decoder.Info.Height is <= 0 or > 8192
            || (long)decoder.Info.Width * decoder.Info.Height > 16_000_000)
            throw new InvalidDataException("REFERENCE_IMAGE_METADATA_INVALID");
        var info = new SKImageInfo(decoder.Info.Width, decoder.Info.Height,
            SKColorType.Bgra8888, SKAlphaType.Premul);
        var pixels = new byte[checked(info.RowBytes * info.Height)];
        if (decoder.GetPixels(info, pixels) != SKCodecResult.Success)
            throw new InvalidDataException("REFERENCE_IMAGE_DECODE_FAILED");
        cancellationToken.ThrowIfCancellationRequested();
        return new(info.Width, info.Height, info.RowBytes, pixels);
    }
}
