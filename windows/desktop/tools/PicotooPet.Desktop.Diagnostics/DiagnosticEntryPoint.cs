using System.Net;
using System.Reflection;
using System.Runtime.ExceptionServices;
using System.Text.Json;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Diagnostics;

/// <summary>为真实双机验收提供局域网直连和仅限预任务阶段的有界恢复。</summary>
internal static class DiagnosticEntryPoint
{
    private const int MaximumAttempts = 3;
    private static readonly TimeSpan RetryDelay = TimeSpan.FromMilliseconds(750);

    private static async Task<int> Main(string[] args)
    {
        ConfigureDirectLanTransport();
        if (args.Contains("--self-test", StringComparer.OrdinalIgnoreCase))
        {
            RunRetryClassifierSelfTest();
            return await InvokeLegacyMainAsync(args).ConfigureAwait(false);
        }

        var outputPath = FindArgument(args, "--output");
        var lastExitCode = 2;
        try
        {
            return await RetryableOperation.ExecuteAsync(
                async cancellationToken =>
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    lastExitCode = await InvokeLegacyMainAsync(args).ConfigureAwait(false);
                    if (lastExitCode == 0 || !CanRetryBeforeTaskCreation(outputPath))
                    {
                        return lastExitCode;
                    }
                    throw new RetryableDiagnosticNetworkException();
                },
                exception => exception is RetryableDiagnosticNetworkException,
                maxAttempts: MaximumAttempts,
                retryDelay: RetryDelay,
                cancellationToken: CancellationToken.None).ConfigureAwait(false);
        }
        catch (RetryableDiagnosticNetworkException)
        {
            return lastExitCode;
        }
    }

    private static void ConfigureDirectLanTransport()
    {
        HttpClient.DefaultProxy = new DirectConnectionProxy();
        Environment.SetEnvironmentVariable("HTTP_PROXY", null);
        Environment.SetEnvironmentVariable("HTTPS_PROXY", null);
        Environment.SetEnvironmentVariable("ALL_PROXY", null);
        Environment.SetEnvironmentVariable("NO_PROXY", "*");
    }

    private static async Task<int> InvokeLegacyMainAsync(string[] args)
    {
        var method = typeof(Program).GetMethod(
            "Main",
            BindingFlags.NonPublic | BindingFlags.Static,
            binder: null,
            types: new[] { typeof(string[]) },
            modifiers: null)
            ?? throw new MissingMethodException(typeof(Program).FullName, "Main");
        try
        {
            var task = method.Invoke(null, new object?[] { args }) as Task<int>
                ?? throw new InvalidOperationException("诊断入口没有返回 Task<int>。");
            return await task.ConfigureAwait(false);
        }
        catch (TargetInvocationException exception) when (exception.InnerException is not null)
        {
            ExceptionDispatchInfo.Capture(exception.InnerException).Throw();
            throw;
        }
    }

    private static bool CanRetryBeforeTaskCreation(string? outputPath)
    {
        if (string.IsNullOrWhiteSpace(outputPath) || !File.Exists(outputPath))
        {
            return false;
        }
        try
        {
            using var report = JsonDocument.Parse(File.ReadAllBytes(outputPath));
            var root = report.RootElement;
            if (!root.TryGetProperty("status", out var status)
                || !string.Equals(status.GetString(), "fail", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
            if (root.TryGetProperty("sample_task_first_id", out var firstTask)
                && firstTask.ValueKind is not JsonValueKind.Null
                && !string.IsNullOrWhiteSpace(firstTask.GetString()))
            {
                return false;
            }
            if (!root.TryGetProperty("errors", out var errors)
                || errors.ValueKind is not JsonValueKind.Array)
            {
                return false;
            }
            return errors.EnumerateArray()
                .Where(error => error.ValueKind is JsonValueKind.String)
                .Select(error => error.GetString() ?? string.Empty)
                .Any(error =>
                    error.Contains("NETWORK_ERROR", StringComparison.OrdinalIgnoreCase)
                    || error.Contains("NETWORK_TIMEOUT", StringComparison.OrdinalIgnoreCase)
                    || error.Contains("无法连接 Mac Core", StringComparison.Ordinal));
        }
        catch (JsonException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static string? FindArgument(string[] args, string name)
    {
        for (var index = 0; index + 1 < args.Length; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }
        return null;
    }

    private static void RunRetryClassifierSelfTest()
    {
        var path = Path.Combine(Path.GetTempPath(), $"picotoo-diagnostic-retry-{Guid.NewGuid():N}.json");
        try
        {
            File.WriteAllText(
                path,
                "{\"status\":\"fail\",\"sample_task_first_id\":null,\"errors\":[\"NETWORK_ERROR\"]}");
            if (!CanRetryBeforeTaskCreation(path))
            {
                throw new InvalidOperationException("预任务网络错误未被识别为可重试。");
            }
            File.WriteAllText(
                path,
                "{\"status\":\"fail\",\"sample_task_first_id\":\"task-1\",\"errors\":[\"NETWORK_ERROR\"]}");
            if (CanRetryBeforeTaskCreation(path))
            {
                throw new InvalidOperationException("已创建任务后不应重启整轮诊断。");
            }
            File.WriteAllText(
                path,
                "{\"status\":\"fail\",\"sample_task_first_id\":null,\"errors\":[\"AUTH_FAILED\"]}");
            if (CanRetryBeforeTaskCreation(path))
            {
                throw new InvalidOperationException("永久认证错误不应重试。");
            }
        }
        finally
        {
            try
            {
                File.Delete(path);
            }
            catch (IOException)
            {
                // 自检临时文件清理失败不改变重试分类结论。
            }
            catch (UnauthorizedAccessException)
            {
                // 自检临时文件清理失败不改变重试分类结论。
            }
        }
    }

    private sealed class RetryableDiagnosticNetworkException : Exception
    {
    }

    private sealed class DirectConnectionProxy : IWebProxy
    {
        public ICredentials? Credentials { get; set; }

        public Uri? GetProxy(Uri destination) => destination;

        public bool IsBypassed(Uri host) => true;
    }
}
