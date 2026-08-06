using System.Diagnostics;
using System.Runtime.Versioning;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>固定 Broker 进程错误；不携带 stdout、stderr、路径或命令。</summary>
public sealed class BrokerProcessException : Exception
{
    /// <summary>创建一个只含固定错误码和安全文案的进程异常。</summary>
    public BrokerProcessException(string code, string message, Exception? inner = null)
        : base(message, inner)
    {
        Code = code;
    }

    /// <summary>供 Session 映射到 Mac Core 安全事实的固定错误码。</summary>
    public string Code { get; }
}

/// <summary>以固定参数启动同一预编译 EXE，并通过 Job Object 约束完整进程树。</summary>
public static class DevBrokerProcessRunner
{
    private const int MaxStandardOutputBytes = 64 * 1024;
    private const int MaxStandardErrorBytes  = 64 * 1024;
    private const int MaxEnvelopeFileBytes   = 64 * 1024;

    private static readonly HashSet<string> EnvelopeProperties = new(StringComparer.Ordinal)
    {
        "schema_version",
        "session_id",
        "handoff_id",
        "return_id",
        "provider",
        "request_digest",
        "package_digest",
        "sandbox_digest",
        "files",
    };

    private static readonly HashSet<string> FileProperties = new(StringComparer.Ordinal)
    {
        "name",
        "content",
    };

    private static readonly UTF8Encoding StrictUtf8 = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling      = JsonUnmappedMemberHandling.Disallow,
    };

    /// <summary>创建沙盒、启动固定子进程、读取有界 JSON 并清理沙盒。</summary>
    public static async Task<MockBrokerReturnEnvelope> RunAsync(
        BrokerSessionCreateResult session,
        HandoffRecord handoff,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(handoff);
        ValidateBindings(session, handoff);
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Mock Dev Broker 只在 Windows 运行。");
        }

        var executable = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(executable)
            || !string.Equals(Path.GetExtension(executable), ".exe", StringComparison.OrdinalIgnoreCase))
        {
            throw new BrokerProcessException(
                "BROKER_EXECUTABLE_INVALID",
                "无法解析当前预编译 Windows 应用。");
        }

        var paths = BrokerSandboxPaths.FromLocalAppData(session.Record.SessionId);
        BrokerSandboxBuilder.Prepare(
            paths,
            new MockBrokerSessionInput(
                "1.0.0",
                session.Record.SessionId,
                session.Record.HandoffId,
                session.Record.RequestDigest,
                session.Record.PackageDigest,
                handoff.BaseCommit));

        MockBrokerReturnEnvelope envelope;
        try
        {
            envelope = await RunChildAsync(
                    executable,
                    paths,
                    session.Record.TimeoutSeconds,
                    cancellationToken)
                .ConfigureAwait(false);
        }
        catch (Exception operationError)
        {
            try
            {
                BrokerSandboxBuilder.Cleanup(paths);
            }
            catch (Exception cleanupError) when (cleanupError is IOException
                or UnauthorizedAccessException
                or InvalidOperationException)
            {
                throw new BrokerProcessException(
                    "BROKER_PROCESS_CLEANUP_FAILED",
                    "Mock Broker 失败后沙盒清理未完成。",
                    new AggregateException(operationError, cleanupError));
            }
            throw;
        }

        try
        {
            BrokerSandboxBuilder.Cleanup(paths);
        }
        catch (Exception cleanupError) when (cleanupError is IOException
            or UnauthorizedAccessException
            or InvalidOperationException)
        {
            throw new BrokerProcessException(
                "BROKER_PROCESS_CLEANUP_FAILED",
                "Mock Broker 沙盒清理失败。",
                cleanupError);
        }
        return envelope;
    }

    [SupportedOSPlatform("windows")]
    private static async Task<MockBrokerReturnEnvelope> RunChildAsync(
        string executable,
        BrokerSandboxPaths paths,
        int timeoutSeconds,
        CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName               = executable,
            UseShellExecute        = false,
            CreateNoWindow         = true,
            RedirectStandardOutput = true,
            RedirectStandardError  = true,
            StandardOutputEncoding = StrictUtf8,
            StandardErrorEncoding  = StrictUtf8,
            WorkingDirectory       = paths.Root,
        };
        startInfo.ArgumentList.Add("--dev-broker-mock-child");
        startInfo.ArgumentList.Add("--session-id");
        startInfo.ArgumentList.Add(Path.GetFileName(paths.Root));

        using var process = new Process { StartInfo = startInfo };
        using var job     = new WindowsJobObject();
        try
        {
            if (!process.Start())
            {
                throw new BrokerProcessException(
                    "BROKER_PROCESS_START_FAILED",
                    "Mock Broker 子进程未能启动。");
            }
            job.Assign(process);
        }
        catch (BrokerProcessException)
        {
            throw;
        }
        catch (Exception exception) when (exception is InvalidOperationException
            or System.ComponentModel.Win32Exception)
        {
            throw new BrokerProcessException(
                "BROKER_PROCESS_START_FAILED",
                "Mock Broker 子进程启动或 Job Object 绑定失败。",
                exception);
        }

        var stdoutTask = ReadBoundedUtf8Async(
            process.StandardOutput.BaseStream,
            MaxStandardOutputBytes);
        var stderrTask = ReadBoundedUtf8Async(
            process.StandardError.BaseStream,
            MaxStandardErrorBytes);
        using var timeoutSource = new CancellationTokenSource(
            TimeSpan.FromSeconds(timeoutSeconds));
        using var linkedSource = CancellationTokenSource.CreateLinkedTokenSource(
            cancellationToken,
            timeoutSource.Token);
        try
        {
            await process.WaitForExitAsync(linkedSource.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            job.Dispose();
            await WaitForContainedExitAsync(process).ConfigureAwait(false);
            throw;
        }
        catch (OperationCanceledException exception)
        {
            job.Dispose();
            await WaitForContainedExitAsync(process).ConfigureAwait(false);
            throw new BrokerProcessException(
                "BROKER_TIMED_OUT",
                "Mock Broker 超过固定 30 秒时限。",
                exception);
        }

        string stdout;
        string stderr;
        try
        {
            stdout = await stdoutTask.ConfigureAwait(false);
            stderr = await stderrTask.ConfigureAwait(false);
        }
        catch (BrokerProcessException)
        {
            throw;
        }
        catch (DecoderFallbackException exception)
        {
            throw new BrokerProcessException(
                "BROKER_OUTPUT_INVALID",
                "Mock Broker 输出不是严格 UTF-8。",
                exception);
        }

        if (process.ExitCode != 0)
        {
            _ = stdout;
            _ = stderr;
            throw new BrokerProcessException(
                "BROKER_CHILD_FAILED",
                "Mock Broker 子进程返回固定失败状态。");
        }

        _ = stdout;
        _ = stderr;
        return ParseEnvelope(ReadBoundedEnvelopeFile(paths));
    }

    private static string ReadBoundedEnvelopeFile(BrokerSandboxPaths paths)
    {
        try
        {
            BrokerSandboxBuilder.RejectExistingReparsePoint(paths.Root);
            var info = new FileInfo(paths.ReturnEnvelopePath);
            if (!info.Exists || info.Length <= 0 || info.Length > MaxEnvelopeFileBytes)
            {
                throw new BrokerProcessException(
                    "BROKER_OUTPUT_INVALID",
                    "Mock Broker 固定 Return 文件不存在、为空或超过 64 KiB。 ");
            }
            if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new BrokerProcessException(
                    "BROKER_OUTPUT_INVALID",
                    "Mock Broker 固定 Return 文件不能是 reparse point。");
            }

            var expectedLength = checked((int)info.Length);
            var bytes          = new byte[expectedLength];
            using var stream = new FileStream(
                paths.ReturnEnvelopePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                bufferSize: 8 * 1024,
                FileOptions.SequentialScan);
            var total = 0;
            while (total < bytes.Length)
            {
                var read = stream.Read(bytes, total, bytes.Length - total);
                if (read == 0)
                {
                    break;
                }
                total = checked(total + read);
            }
            if (total != bytes.Length || stream.ReadByte() != -1)
            {
                throw new BrokerProcessException(
                    "BROKER_OUTPUT_INVALID",
                    "Mock Broker 固定 Return 文件在读取期间发生变化。");
            }
            return StrictUtf8.GetString(bytes);
        }
        catch (BrokerProcessException)
        {
            throw;
        }
        catch (DecoderFallbackException exception)
        {
            throw new BrokerProcessException(
                "BROKER_OUTPUT_INVALID",
                "Mock Broker 固定 Return 文件不是严格 UTF-8。",
                exception);
        }
        catch (Exception exception) when (exception is IOException
            or UnauthorizedAccessException
            or InvalidOperationException)
        {
            throw new BrokerProcessException(
                "BROKER_OUTPUT_INVALID",
                "Mock Broker 固定 Return 文件无法安全读取。",
                exception);
        }
    }

    private static async Task<string> ReadBoundedUtf8Async(Stream stream, int maxBytes)
    {
        using var buffer = new MemoryStream(capacity: Math.Min(maxBytes, 16 * 1024));
        var block = new byte[8 * 1024];
        var total = 0;
        while (true)
        {
            var read = await stream.ReadAsync(block.AsMemory()).ConfigureAwait(false);
            if (read == 0)
            {
                return StrictUtf8.GetString(buffer.ToArray());
            }
            total = checked(total + read);
            if (total > maxBytes)
            {
                throw new BrokerProcessException(
                    "BROKER_OUTPUT_TOO_LARGE",
                    "Mock Broker 输出超过 64 KiB 安全上限。");
            }
            await buffer.WriteAsync(block.AsMemory(0, read)).ConfigureAwait(false);
        }
    }

    private static MockBrokerReturnEnvelope ParseEnvelope(string json)
    {
        try
        {
            using var document = JsonDocument.Parse(json, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling     = JsonCommentHandling.Disallow,
                MaxDepth            = 32,
            });
            ValidateEnvelopeShape(document.RootElement);
            return JsonSerializer.Deserialize<MockBrokerReturnEnvelope>(json, JsonOptions)
                ?? throw new BrokerProcessException(
                    "BROKER_OUTPUT_INVALID",
                    "Mock Broker 返回空 JSON。");
        }
        catch (JsonException exception)
        {
            throw new BrokerProcessException(
                "BROKER_OUTPUT_INVALID",
                "Mock Broker 返回的 JSON 不符合固定合同。",
                exception);
        }
    }

    private static void ValidateEnvelopeShape(JsonElement root)
    {
        if (root.ValueKind is not JsonValueKind.Object)
        {
            throw new JsonException("Envelope root must be an object.");
        }
        var actual = root.EnumerateObject().Select(property => property.Name).ToHashSet(
            StringComparer.Ordinal);
        if (!actual.SetEquals(EnvelopeProperties))
        {
            throw new JsonException("Envelope properties do not match the fixed contract.");
        }
        var files = root.GetProperty("files");
        if (files.ValueKind is not JsonValueKind.Array || files.GetArrayLength() != 10)
        {
            throw new JsonException("Envelope file count is invalid.");
        }
        foreach (var file in files.EnumerateArray())
        {
            if (file.ValueKind is not JsonValueKind.Object)
            {
                throw new JsonException("Envelope file entry is invalid.");
            }
            var properties = file.EnumerateObject().Select(property => property.Name).ToHashSet(
                StringComparer.Ordinal);
            if (!properties.SetEquals(FileProperties))
            {
                throw new JsonException("Envelope file properties are invalid.");
            }
        }
    }

    private static void ValidateBindings(
        BrokerSessionCreateResult session,
        HandoffRecord handoff)
    {
        if (!string.Equals(session.Record.Status, "reserved", StringComparison.Ordinal)
            || !string.Equals(
                session.Record.Provider,
                "local-mock-dev-broker",
                StringComparison.Ordinal)
            || session.Record.TimeoutSeconds != 30
            || !string.Equals(session.Record.HandoffId, handoff.HandoffId, StringComparison.Ordinal)
            || !string.Equals(
                session.Record.RequestDigest,
                handoff.RequestDigest,
                StringComparison.Ordinal)
            || !string.Equals(
                session.Record.PackageDigest,
                handoff.PackageDigest,
                StringComparison.Ordinal)
            || session.Capability.Length != 64)
        {
            throw new ArgumentException("Broker Session 与 Handoff 安全投影不匹配。");
        }
    }

    private static async Task WaitForContainedExitAsync(Process process)
    {
        using var cleanupTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        try
        {
            await process.WaitForExitAsync(cleanupTimeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException exception)
        {
            throw new BrokerProcessException(
                "BROKER_PROCESS_CLEANUP_FAILED",
                "Mock Broker 进程树未在清理时限内退出。",
                exception);
        }
    }
}
