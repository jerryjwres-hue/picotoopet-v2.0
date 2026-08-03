using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>确保诊断结果在客户端也受 64 KiB 硬上限保护。</summary>
internal static class BoundedDiagnosticResultSmokeTests
{
    public static async Task RunAsync()
    {
        using var httpClient = new HttpClient(new OversizedResultHandler())
        {
            BaseAddress = new Uri("http://127.0.0.1:18186/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(httpClient, "fixture-token");

        try
        {
            await client.GetTaskResultAsync(
                "oversized-result",
                CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException(
                "超过 64 KiB 的诊断结果未被客户端拒绝。");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "RESPONSE_TOO_LARGE",
                exception.Code,
                "超大诊断结果没有返回稳定错误码");
            SmokeAssert.True(
                !exception.Retryable,
                "合同超限不是瞬态错误，不应自动重试");
        }
    }

    private sealed class OversizedResultHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new UnknownLengthContent(64 * 1024 + 1),
            };
            return Task.FromResult(response);
        }
    }

    private sealed class UnknownLengthContent(int sizeBytes) : HttpContent
    {
        protected override async Task SerializeToStreamAsync(
            Stream stream,
            TransportContext? context)
        {
            var block = Encoding.UTF8.GetBytes(new string(' ', 4096));
            var remaining = sizeBytes;
            while (remaining > 0)
            {
                var count = Math.Min(block.Length, remaining);
                await stream.WriteAsync(block.AsMemory(0, count)).ConfigureAwait(false);
                remaining -= count;
            }
        }

        protected override bool TryComputeLength(out long length)
        {
            length = 0;
            return false;
        }
    }
}
