using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>异常服务器不得通过无界错误正文拖大 Windows 客户端内存。</summary>
internal static class BoundedApiErrorSmokeTests
{
    public static async Task RunAsync()
    {
        using var httpClient = new HttpClient(new OversizedErrorHandler())
        {
            BaseAddress = new Uri("http://127.0.0.1:18187/", UriKind.Absolute),
        };
        await using var client = new MacCoreClient(httpClient, "fixture-token");

        try
        {
            await client.GetHealthAsync(CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("超大错误响应未转换为受控 API 异常。");
        }
        catch (ApiException exception)
        {
            SmokeAssert.Equal(
                "HTTP_ERROR",
                exception.Code,
                "超大错误正文不应被解析为任意服务端错误码");
            SmokeAssert.Equal(
                (int)HttpStatusCode.ServiceUnavailable,
                exception.StatusCode,
                "HTTP 状态码没有保留");
            SmokeAssert.True(
                exception.Retryable,
                "503 仍应保留可重试语义");
            SmokeAssert.True(
                exception.Message.Length < 256,
                "超大错误正文不应进入用户消息");
        }
    }

    private sealed class OversizedErrorHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
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
            var block = Encoding.UTF8.GetBytes(new string('x', 4096));
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
