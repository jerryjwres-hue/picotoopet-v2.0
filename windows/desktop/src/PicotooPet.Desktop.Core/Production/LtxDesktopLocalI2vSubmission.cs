using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

namespace PicotooPet.Desktop.Core.Production;

/// <summary>
/// Internal vendor transport result. The caller must eventually be the signed
/// LTX Worker path; this is not Core approval, a lease, or a CommitResult.
/// </summary>
internal sealed record LtxDesktopSubmissionReceipt(
    string GenerationId, string StartFrameAssetId, string FirstFrameSha256,
    string JournalDigest);

public sealed partial class LtxDesktopLocalI2vPreflightClient
{
    /// <summary>
    /// Internal one-shot transport only. No production caller until the Core
    /// supports an LTX-specific signed Plan and attempt reservation.
    /// The existing GPU lock and journal are mandatory, not a substitute
    /// for that future authorization.
    /// </summary>
    internal async Task<LtxDesktopSubmissionReceipt> SubmitOnceTransportAsync(
        LtxDesktopI2vDraft draft, string localSettingsFile,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        string jobId, string taskId, string planDigest,
        CancellationToken cancellationToken = default) =>
        SubmitTransportCoreAsync(draft, localSettingsFile, journal, gpu, jobId, taskId,
            planDigest, null, null, cancellationToken);

    // 01. The signed Worker must supply its live Core lease recheck. This is
    //     still internal transport, not a replacement for Core authorization.
    internal Task<LtxDesktopSubmissionReceipt> SubmitClaimedOnceTransportAsync(
        LtxDesktopI2vDraft draft, string localSettingsFile,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        string jobId, string taskId, string planDigest, string expectedIntentDigest,
        Func<CancellationToken, Task> recheckLease, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(recheckLease);
        return SubmitTransportCoreAsync(draft, localSettingsFile, journal, gpu, jobId,
            taskId, planDigest, expectedIntentDigest, recheckLease, cancellationToken);
    }

    private async Task<LtxDesktopSubmissionReceipt> SubmitTransportCoreAsync(
        LtxDesktopI2vDraft draft, string localSettingsFile,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu,
        string jobId, string taskId, string planDigest, string? expectedIntentDigest,
        Func<CancellationToken, Task>? recheckLease, CancellationToken cancellationToken)
    {
        // 02. Reuse the existing cross-process GPU lock. Do not permit a
        //     parallel renderer or any unsettled submission (including Wan).
        ArgumentNullException.ThrowIfNull(journal);
        ArgumentNullException.ThrowIfNull(gpu);
        gpu.RequireOwnedBy(journal);
        if (!Guid.TryParseExact(jobId, "D", out _)
            || !Guid.TryParseExact(taskId, "D", out _)
            || !IsSha(planDigest))
        {
            throw new InvalidOperationException("LTX_SUBMISSION_SCOPE_INVALID");
        }
        var signed = expectedIntentDigest is not null;
        var prior = journal.Read(jobId, taskId);
        var pending = journal.Pending();
        if (signed != (draft.SourceCreativePackageDigest is not null)
            || (signed && (!IsSha(expectedIntentDigest!) || recheckLease is null)))
            throw new InvalidOperationException("LTX_SUBMISSION_SOURCE_SCOPE_INVALID");
        if (signed
            ? prior is null || !prior.IsLtx || prior.Phase != "Claimed"
                || prior.PlanDigest != planDigest || prior.GraphDigest != expectedIntentDigest
                || pending.Count != 1 || pending[0] != prior
            : prior is not null || pending.Count != 0)
            throw new InvalidOperationException("LTX_SUBMISSION_RECONCILIATION_REQUIRED");

        // 02. Repeat local capability checks immediately before upload.
        //     Copy the exact bounded input bytes and rehash them; never
        //     upload a path that may have changed after preflight.
        var readiness = await PreflightAsync(draft, localSettingsFile, cancellationToken)
            .ConfigureAwait(false);
        var frame = Path.GetFullPath(draft.FirstFrameFile);
        byte[] bytes;
        await using (var source = new FileStream(frame, FileMode.Open, FileAccess.Read,
            FileShare.Read, 128 * 1024, FileOptions.Asynchronous))
        {
            if (source.Length is <= 0 or > MaxFirstFrameBytes
                || (File.GetAttributes(frame) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("LTX_SUBMISSION_FRAME_INVALID");
            bytes = new byte[checked((int)source.Length)];
            await source.ReadExactlyAsync(bytes, cancellationToken).ConfigureAwait(false);
            if (source.ReadByte() != -1)
                throw new InvalidDataException("LTX_SUBMISSION_FRAME_CHANGED");
        }
        var digest = Convert.ToHexStringLower(SHA256.HashData(bytes));
        if (digest != draft.FirstFrameSha256)
            throw new InvalidDataException("LTX_SUBMISSION_FRAME_CHANGED");
        var png = bytes.Length >= 8 && bytes.AsSpan(0, 8)
            .SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        var jpg = bytes.Length >= 4 && bytes[0] == 0xff && bytes[1] == 0xd8
            && bytes[^2] == 0xff && bytes[^1] == 0xd9;
        if (!png && !jpg)
            throw new InvalidDataException("LTX_SUBMISSION_FRAME_FORMAT_INVALID");

        // 03. Pin the exact intent and source digest before the first POST.
        //     Deliberately reuse the existing journal format; never put a
        //     token, signed URL, private path or raw prompt in its record.
        var payload = readiness.VendorSubmissionTemplate.DeepClone().AsObject();
        var requestDigest = SubmissionIntentDigest(draft, payload);
        if (signed && requestDigest != expectedIntentDigest)
            throw new InvalidOperationException("LTX_SUBMISSION_SIGNED_INTENT_MISMATCH");
        var state = new ProductionSubmission(jobId, taskId, planDigest,
            requestDigest, "Submitting", null, Renderer: ProductionSubmission.LtxRenderer);

        gpu.RequireOwnedBy(journal);
        cancellationToken.ThrowIfCancellationRequested();
        // 03. Recheck the exact signed reservation immediately before upload.
        if (recheckLease is not null) await recheckLease(cancellationToken).ConfigureAwait(false);
        gpu.RequireOwnedBy(journal);
        cancellationToken.ThrowIfCancellationRequested();
        journal.Save(state);

        // 04. The durable marker exists BEFORE the upload. Any timeout,
        //     cancellation, malformed receipt or process crash keeps it.
        //     No automatic retry, including an ambiguous image upload.
        string assetId;
        using (var form = new MultipartFormDataContent())
        {
            var part = new ByteArrayContent(bytes);
            part.Headers.ContentType = new MediaTypeHeaderValue(png ? "image/png" : "image/jpeg");
            form.Add(part, "file", png ? "first-frame.png" : "first-frame.jpg");
            var uploaded = await PostLtxOnceAsync("api/assets/upload", form, cancellationToken)
                .ConfigureAwait(false);
            assetId = ReadText(uploaded, "id") ?? "";
            if (!Guid.TryParseExact(assetId, "D", out _)
                || ReadText(uploaded, "media_kind") != "image")
                throw new InvalidDataException("LTX_SUBMISSION_UPLOAD_RECEIPT_UNVERIFIED");
        }

        // 05. Bind the vendor's actual returned asset UUID, not the Core
        //     character asset ID or a fabricated UUID. Exactly one POST.
        // Persist upload receipt before issuing generation POST. A restart
        // must know the exact vendor asset, even if generation POST is lost.
        state = state with { VendorStartFrameAssetId = assetId };
        journal.Save(state);
        ((JsonObject)payload["inputs"]!["startFrame"]!)["assetId"] = assetId;
        // 04. Revocation between upload and generation must prevent GPU POST.
        if (recheckLease is not null) await recheckLease(cancellationToken).ConfigureAwait(false);
        gpu.RequireOwnedBy(journal);
        using var body = new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json");
        var created = await PostLtxOnceAsync("api/generations/image-to-video", body,
            cancellationToken).ConfigureAwait(false);
        var generationId = ReadText(created, "id") ?? "";
        if (!Guid.TryParseExact(generationId, "D", out _))
            throw new InvalidDataException("LTX_SUBMISSION_GENERATION_RECEIPT_UNVERIFIED");

        // 06. Record the vendor ID in the renderer-tagged journal slot.
        //     The legacy Wan recovery loop must not consume this entry:
        //     a dedicated engine-aware recovery/authorization caller is
        //     required before enabling this component in production.
        journal.Save(state with { Phase = "Submitted", PromptId = generationId });
        return new LtxDesktopSubmissionReceipt(generationId, assetId, digest, requestDigest);
    }

    // 05. Match Core's vendor_intent_digest exactly for the formal source.
    //     Preserve the standalone StoryPack digest for its existing fixtures.
    internal static string SubmissionIntentDigest(LtxDesktopI2vDraft draft, JsonObject payload)
    {
        var identity = new JsonObject
        {
            ["engine"] = "ltx.desktop.local.i2v.v1",
            [draft.SourceCreativePackageDigest is null ? "source_storypack_sha256" : "creative_package_digest"]
                = draft.SourceCreativePackageDigest ?? draft.SourceStoryPackSha256,
            ["first_frame_sha256"] = draft.FirstFrameSha256,
            ["vendor_request"] = payload.DeepClone(),
        };
        return ProductionSubmissionJournal.GraphDigest(identity);
    }

    private async Task<JsonObject> PostLtxOnceAsync(string path, HttpContent content,
        CancellationToken ct)
    {
        // 07. Only the two literal local vendor POST endpoints are allowed.
        //     The normal client constructor disables redirects and proxies.
        if (path is not ("api/assets/upload" or "api/generations/image-to-video"))
            throw new InvalidOperationException("LTX_SUBMISSION_ENDPOINT_INVALID");
        try
        {
            using var message = new HttpRequestMessage(HttpMethod.Post, path) { Content = content };
            using var response = await _http.SendAsync(message,
                HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            if (!response.IsSuccessStatusCode)
                throw new InvalidDataException("LTX_SUBMISSION_VENDOR_REJECTED_OR_UNCERTAIN");
            if (response.Content.Headers.ContentLength is <= 0 or > MaxJsonBytes)
                throw new InvalidDataException("LTX_SUBMISSION_RECEIPT_INVALID");
            await using var input = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            using var buffer = new MemoryStream();
            var chunk = new byte[8192];
            while (true)
            {
                var count = await input.ReadAsync(chunk, ct).ConfigureAwait(false);
                if (count == 0) break;
                if (buffer.Length + count > MaxJsonBytes)
                    throw new InvalidDataException("LTX_SUBMISSION_RECEIPT_INVALID");
                buffer.Write(chunk, 0, count);
            }
            return JsonNode.Parse(buffer.ToArray()) as JsonObject
                ?? throw new InvalidDataException("LTX_SUBMISSION_RECEIPT_INVALID");
        }
        catch (HttpRequestException)
        {
            // Never expose credentials or private vendor response body.
            throw new IOException("LTX_SUBMISSION_TRANSPORT_UNCERTAIN");
        }
    }
}
