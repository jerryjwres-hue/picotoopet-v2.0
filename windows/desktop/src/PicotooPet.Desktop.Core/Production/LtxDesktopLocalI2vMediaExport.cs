using System.Net;
using System.Security.Cryptography;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>Exact downloaded bytes, not a verified decoded video or Core result.</summary>
public sealed record LtxDesktopExportedCandidate(
    LtxDesktopGenerationInspection Inspection,
    string LocalFileName,
    string Sha256,
    long Bytes);

public sealed partial class LtxDesktopLocalI2vPreflightClient
{
    private const long MaxExportBytes = 256L * 1024 * 1024;

    /// <summary>Reuses the exact completed-generation check; GET only, never rerenders.</summary>
    public async Task<LtxDesktopExportedCandidate> ExportCompletedCandidateAsync(
        LtxDesktopGenerationExpectation expected, string candidateDirectory,
        CancellationToken cancellationToken = default)
    {
        // 01. Restrict output to an existing fully qualified local directory.
        //     Reject reparse points in all ancestors and refuse overwrite.
        if (!Path.IsPathFullyQualified(candidateDirectory)
            || candidateDirectory.StartsWith(@"\\", StringComparison.Ordinal)
            || !Directory.Exists(candidateDirectory))
        {
            throw new InvalidDataException("LTX_EXPORT_DIRECTORY_INVALID");
        }
        var directory = new DirectoryInfo(Path.GetFullPath(candidateDirectory));
        for (DirectoryInfo? ancestor = directory; ancestor is not null; ancestor = ancestor.Parent)
        {
            if ((ancestor.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("LTX_EXPORT_DIRECTORY_INVALID");
            }
        }

        // 02. Re-read exact vendor generation. The signed URL never leaves this
        //     method and is never stored in receipts or candidate filenames.
        var (inspection, signedPath) = await InspectGenerationForExportAsync(
            expected, cancellationToken).ConfigureAwait(false);
        var extension = inspection.MediaType == "video/mp4" ? ".mp4" : ".webm";
        var fileName = inspection.GenerationId + "-video-" + inspection.VideoAssetId + extension;
        var target = Path.Combine(directory.FullName, fileName);
        if (File.Exists(target) || Directory.Exists(target))
        {
            throw new IOException("LTX_EXPORT_ALREADY_EXISTS");
        }

        // 03. Existing paired, fixed-loopback transport. No redirects or
        //     proxy in Create(); reject partial responses and wrong MIME.
        //     Sanitize transport errors rather than leaking the signed URL.
        var temp = Path.Combine(directory.FullName, Guid.NewGuid().ToString("N") + ".partial");
        try
        {
            using var message = new HttpRequestMessage(HttpMethod.Get, signedPath);
            using var response = await _http.SendAsync(message,
                HttpCompletionOption.ResponseHeadersRead, cancellationToken).ConfigureAwait(false);
            if (response.StatusCode != HttpStatusCode.OK
                || response.Content.Headers.ContentRange is not null
                || response.Content.Headers.ContentEncoding.Count != 0
                || response.Content.Headers.ContentType?.MediaType != inspection.MediaType)
            {
                throw new InvalidDataException("LTX_EXPORT_MEDIA_RESPONSE_INVALID");
            }
            var declaredBytes = response.Content.Headers.ContentLength;
            if (declaredBytes is <= 0 or > MaxExportBytes)
            {
                throw new InvalidDataException("LTX_EXPORT_MEDIA_SIZE_INVALID");
            }

            // 04. Stream with a fixed bound, actual byte count and incremental
            //     SHA256. Do not trust a remote Content-Length or output name.
            //     Check a container signature, not a fake decode/frame audit.
            using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var prefix = new byte[12];
            var prefixCount = 0;
            var total = 0L;
            await using (var input = await response.Content.ReadAsStreamAsync(cancellationToken)
                .ConfigureAwait(false))
            await using (var output = new FileStream(temp, FileMode.CreateNew,
                FileAccess.Write, FileShare.None, 128 * 1024, FileOptions.Asynchronous))
            {
                var buffer = new byte[128 * 1024];
                while (true)
                {
                    var read = await input.ReadAsync(buffer, cancellationToken).ConfigureAwait(false);
                    if (read == 0) break;
                    total += read;
                    if (total > MaxExportBytes)
                    {
                        throw new InvalidDataException("LTX_EXPORT_MEDIA_SIZE_INVALID");
                    }
                    var copy = Math.Min(read, prefix.Length - prefixCount);
                    if (copy > 0)
                    {
                        Array.Copy(buffer, 0, prefix, prefixCount, copy);
                        prefixCount += copy;
                    }
                    sha.AppendData(buffer, 0, read);
                    await output.WriteAsync(buffer.AsMemory(0, read), cancellationToken)
                        .ConfigureAwait(false);
                }
                if (total < prefix.Length || (declaredBytes.HasValue && declaredBytes.Value != total))
                {
                    throw new InvalidDataException("LTX_EXPORT_MEDIA_INCOMPLETE");
                }
                var signatureOk = inspection.MediaType == "video/mp4"
                    ? prefix.AsSpan(4, 4).SequenceEqual("ftyp"u8)
                    : prefix.AsSpan(0, 4).SequenceEqual(new byte[] { 0x1A, 0x45, 0xDF, 0xA3 });
                if (!signatureOk)
                {
                    throw new InvalidDataException("LTX_EXPORT_CONTAINER_SIGNATURE_INVALID");
                }
                output.Flush(flushToDisk: true);
            }

            // 05. No replacement of old accepted or candidate media. The
            //     downloaded file is not promoted into a production package.
            cancellationToken.ThrowIfCancellationRequested();
            var digest = Convert.ToHexStringLower(sha.GetHashAndReset());
            File.Move(temp, target, overwrite: false);
            return new LtxDesktopExportedCandidate(
                inspection with { MediaBytesDownloaded = true },
                fileName, digest, total);
        }
        catch (HttpRequestException)
        {
            throw new IOException("LTX_EXPORT_TRANSPORT_UNVERIFIED");
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }
}
