using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证诊断采样的有界重试、非重试错误和取消语义。</summary>
internal static class RetryableOperationSmokeTests
{
    public static async Task RunAsync()
    {
        await RetriesTransientFailuresWithBoundedAttemptsAsync().ConfigureAwait(false);
        await DoesNotRetryPermanentFailuresAsync().ConfigureAwait(false);
        await PreservesCancellationAsync().ConfigureAwait(false);
    }

    private static async Task RetriesTransientFailuresWithBoundedAttemptsAsync()
    {
        var attempts = 0;
        var result = await RetryableOperation.ExecuteAsync(
            _ =>
            {
                attempts++;
                if (attempts < 3)
                {
                    throw new ApiException(
                        "NETWORK_ERROR",
                        "transient",
                        retryable: true,
                        traceId: null,
                        statusCode: 0);
                }
                return Task.FromResult(42);
            },
            exception => exception is ApiException { Retryable: true },
            maxAttempts: 3,
            retryDelay: TimeSpan.Zero,
            cancellationToken: CancellationToken.None).ConfigureAwait(false);

        Assert(result == 42, "可重试操作未返回最终结果。");
        Assert(attempts == 3, "可重试操作没有遵守最大尝试次数。");
    }

    private static async Task DoesNotRetryPermanentFailuresAsync()
    {
        var attempts = 0;
        try
        {
            await RetryableOperation.ExecuteAsync<int>(
                _ =>
                {
                    attempts++;
                    throw new ApiException(
                        "AUTH_FAILED",
                        "permanent",
                        retryable: false,
                        traceId: null,
                        statusCode: 401);
                },
                exception => exception is ApiException { Retryable: true },
                maxAttempts: 3,
                retryDelay: TimeSpan.Zero,
                cancellationToken: CancellationToken.None).ConfigureAwait(false);
            throw new InvalidOperationException("永久错误被错误地吞掉。");
        }
        catch (ApiException exception) when (exception.Code == "AUTH_FAILED")
        {
            Assert(attempts == 1, "永久错误不应被重试。");
        }
    }

    private static async Task PreservesCancellationAsync()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var attempts = 0;
        try
        {
            await RetryableOperation.ExecuteAsync(
                token =>
                {
                    attempts++;
                    token.ThrowIfCancellationRequested();
                    return Task.FromResult(0);
                },
                _ => true,
                maxAttempts: 3,
                retryDelay: TimeSpan.Zero,
                cancellationToken: cancellation.Token).ConfigureAwait(false);
            throw new InvalidOperationException("取消请求被错误地吞掉。");
        }
        catch (OperationCanceledException)
        {
            Assert(attempts == 1, "取消后不应继续重试。");
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
