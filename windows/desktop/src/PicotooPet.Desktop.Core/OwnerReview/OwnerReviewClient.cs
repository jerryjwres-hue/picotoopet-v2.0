using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>
/// 冻结的三个 Core 主人审核端点的薄客户端。凭据仅来自专用存储，
/// 只发往 /api/v1/owner-structured-reviews/*，从不复用设备令牌。
/// </summary>
public sealed class OwnerReviewClient : IDisposable
{
    private const int MaxResponseBytes = 1024 * 1024;
    private const string Root = "api/v1/owner-structured-reviews";
    private readonly HttpClient _http;
    private readonly IOwnerReviewCredentialStore _credentials;
    private readonly bool _ownsHttp;

    /// <summary>创建客户端。<paramref name="handler"/> 仅 Mock 模式使用。</summary>
    public OwnerReviewClient(
        Uri baseAddress,
        OwnerReviewTransportMode mode,
        IOwnerReviewCredentialStore credentials,
        HttpMessageHandler? handler = null)
    {
        ArgumentNullException.ThrowIfNull(baseAddress);
        ArgumentNullException.ThrowIfNull(credentials);
        if (mode == OwnerReviewTransportMode.PinnedSshStdio)
        {
            // A default HttpClientHandler would speak plain direct HTTP to the synthetic authority,
            // and an injected handler is unauthorized. Only the typed factory may build this mode.
            throw new ArgumentException(
                "PinnedSshStdio 只能通过 CreatePinnedSshStdio 构造。", nameof(mode));
        }
        OwnerReviewTransportGate.Require(mode, baseAddress);
        if (mode == OwnerReviewTransportMode.Mock && handler is null)
        {
            throw new ArgumentException("Mock 传输必须注入 HttpMessageHandler。", nameof(handler));
        }
        if (mode != OwnerReviewTransportMode.Mock && handler is not null)
        {
            throw new ArgumentException("只有 Mock 传输可以注入 HttpMessageHandler。", nameof(handler));
        }
        _credentials = credentials;
        _http = handler is null
            ? new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false })
            : new HttpClient(handler, disposeHandler: false);
        _ownsHttp = true;
        _http.BaseAddress = new Uri(baseAddress.GetLeftPart(UriPartial.Authority) + "/");
        _http.Timeout = TimeSpan.FromSeconds(20);
    }

    private OwnerReviewClient(HttpClient http, IOwnerReviewCredentialStore credentials)
    {
        _http = http;
        _credentials = credentials;
        _ownsHttp = true;
    }

    /// <summary>
    /// The only way to build a live-capable client: HTTP is carried by the pinned SSH stdio
    /// handler of <see cref="OwnerReviewSshStdioCandidate"/> and nothing else. No handler or base
    /// URI is accepted, the profile (pinned host key, protected NTFS key/known_hosts) is verified
    /// before any process exists, and no credential is read here. Requires an activation token that
    /// production cannot obtain while the gate is locked.
    /// </summary>
    public static OwnerReviewClient CreatePinnedSshStdio(
        OwnerReviewSshStdioProfile profile,
        IOwnerReviewCredentialStore credentials,
        OwnerReviewSshStdioActivation? activation)
    {
        ArgumentNullException.ThrowIfNull(profile);
        ArgumentNullException.ThrowIfNull(credentials);
        if (activation is null)
        {
            throw new OwnerReviewException(
                OwnerReviewFailureKind.TransportBlocked, 0, "OWNER_REVIEW_SSH_STDIO_NOT_ACTIVATED");
        }
        var address = OwnerReviewSshStdioCandidate.SyntheticAuthority;
        OwnerReviewTransportGate.Require(OwnerReviewTransportMode.PinnedSshStdio, address);
        var handler = OwnerReviewSshStdioCandidate.CreateIsolatedHandler(profile);
        HttpClient? http = null;
        try
        {
            http = new HttpClient(handler, disposeHandler: true)
            {
                BaseAddress = address,
                Timeout = TimeSpan.FromSeconds(20),
            };
            return new OwnerReviewClient(http, credentials);
        }
        catch
        {
            if (http is null)
            {
                handler.Dispose();
            }
            else
            {
                http.Dispose();
            }
            throw;
        }
    }

    public Task<OwnerReviewProposal> GetProposalAsync(string goalId, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(goalId) || goalId.Length > 128 || goalId.Any(c => !IsSafePathChar(c)))
        {
            throw new ArgumentException("Goal ID 格式无效。", nameof(goalId));
        }
        return SendAsync<OwnerReviewProposal>(
            HttpMethod.Get,
            $"{Root}/goals/{Uri.EscapeDataString(goalId)}/proposal",
            body: null,
            idempotencyKey: null,
            expected: 200,
            cancellationToken);
    }

    public Task<OwnerReviewPreview> PreviewAsync(
        OwnerReviewPreviewRequest request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        return SendAsync<OwnerReviewPreview>(
            HttpMethod.Post, $"{Root}/preview", request, null, 200, cancellationToken);
    }

    public Task<OwnerReviewCommit> CommitAsync(
        OwnerReviewCommitRequest request,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrWhiteSpace(idempotencyKey) || idempotencyKey.Length > 200
            || idempotencyKey.Any(c => c < 0x21 || c > 0x7e))
        {
            throw new ArgumentException("Idempotency-Key 必须是 1–200 个可见 ASCII 字符。", nameof(idempotencyKey));
        }
        return SendAsync<OwnerReviewCommit>(
            HttpMethod.Post, $"{Root}/commit", request, idempotencyKey, 201, cancellationToken);
    }

    public void Dispose()
    {
        if (_ownsHttp)
        {
            _http.Dispose();
        }
    }

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        string? idempotencyKey,
        int expected,
        CancellationToken cancellationToken)
    {
        var credential = _credentials.Read();
        if (string.IsNullOrWhiteSpace(credential))
        {
            throw new OwnerReviewException(
                OwnerReviewFailureKind.CredentialMissing, 0, "OWNER_REVIEW_CREDENTIAL_MISSING");
        }

        using var message = new HttpRequestMessage(method, path);
        message.Headers.Authorization = new AuthenticationHeaderValue("Bearer", credential);
        message.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        if (idempotencyKey is not null)
        {
            message.Headers.TryAddWithoutValidation("Idempotency-Key", idempotencyKey);
        }
        if (body is not null)
        {
            message.Content = new StringContent(
                JsonSerializer.Serialize(body, body.GetType(), OwnerReviewWire.Json),
                Encoding.UTF8,
                "application/json");
        }

        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(message, HttpCompletionOption.ResponseContentRead, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (HttpRequestException)
        {
            throw new OwnerReviewException(OwnerReviewFailureKind.Unavailable, 0, "OWNER_REVIEW_UNREACHABLE");
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new OwnerReviewException(OwnerReviewFailureKind.Unavailable, 0, "OWNER_REVIEW_TIMEOUT");
        }

        using (response)
        {
            var text = await ReadBoundedAsync(response, cancellationToken).ConfigureAwait(false);
            if ((int)response.StatusCode != expected)
            {
                throw OwnerReviewException.FromResponse((int)response.StatusCode, text);
            }
            try
            {
                return JsonSerializer.Deserialize<T>(text, OwnerReviewWire.Json)
                    ?? throw new OwnerReviewException(OwnerReviewFailureKind.Other, (int)response.StatusCode, "OWNER_REVIEW_RESPONSE_INVALID");
            }
            catch (JsonException)
            {
                throw new OwnerReviewException(OwnerReviewFailureKind.Other, (int)response.StatusCode, "OWNER_REVIEW_RESPONSE_INVALID");
            }
        }
    }

    private static async Task<string> ReadBoundedAsync(HttpResponseMessage response, CancellationToken token)
    {
        await using var stream = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        using var buffer = new MemoryStream();
        var chunk = new byte[8192];
        int read;
        while ((read = await stream.ReadAsync(chunk, token).ConfigureAwait(false)) > 0)
        {
            if (buffer.Length + read > MaxResponseBytes)
            {
                throw new OwnerReviewException(OwnerReviewFailureKind.Other, (int)response.StatusCode, "OWNER_REVIEW_RESPONSE_TOO_LARGE");
            }
            buffer.Write(chunk, 0, read);
        }
        return Encoding.UTF8.GetString(buffer.GetBuffer(), 0, (int)buffer.Length);
    }

    private static bool IsSafePathChar(char c) =>
        char.IsAsciiLetterOrDigit(c) || c is '-' or '_' or '.' or ':';
}
