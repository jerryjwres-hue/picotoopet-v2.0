using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Channels;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Diagnostics;

/// <summary>使用真实 REST、WebSocket 与 Credential Manager 的双机验收程序。</summary>
internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented               = true,
    };

    /// <summary>执行健康、任务回传与 Ping/Pong 高样本测试，并输出机器可读报告。</summary>
    private static async Task<int> Main(string[] args)
    {
        if (args.Any(argument =>
                string.Equals(argument, "--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            Console.WriteLine("PHASE2_DIAGNOSTICS_SELF_TEST=PASS");
            return 0;
        }

        var options = DiagnosticOptions.Parse(args);
        Directory.CreateDirectory(Path.GetDirectoryName(options.OutputPath) ?? ".");
        try
        {
            var token = new CredentialManagerTokenStore().Read();
            if (string.IsNullOrWhiteSpace(token))
            {
                return await WriteReportAsync(
                    options.OutputPath,
                    DiagnosticReport.Incomplete(options, "Windows Credential Manager 中尚无设备令牌。"));
            }

            var report = await RunAsync(options, token).ConfigureAwait(false);
            return await WriteReportAsync(options.OutputPath, report).ConfigureAwait(false);
        }
        catch (Exception exception)
        {
            var report = DiagnosticReport.Failed(
                options,
                "DIAGNOSTIC_UNHANDLED",
                exception.GetType().Name,
                exception.Message);
            return await WriteReportAsync(options.OutputPath, report).ConfigureAwait(false);
        }
    }

    private static async Task<DiagnosticReport> RunAsync(
        DiagnosticOptions options,
        string token)
    {
        using var overallTimeout = new CancellationTokenSource(options.TotalTimeout);
        var cancellationToken    = overallTimeout.Token;
        var healthLatency        = new LatencyRecorder(Math.Max(128, options.RestSamples));
        var taskSubmitLatency    = new LatencyRecorder(Math.Max(128, options.TaskSamples));
        var taskEventLatency     = new LatencyRecorder(Math.Max(128, options.TaskSamples));
        var socketLatency        = new LatencyRecorder(Math.Max(128, options.SocketSamples));
        var taskEvents = Channel.CreateBounded<TaskRecord>(new BoundedChannelOptions(
            Math.Clamp(options.TaskSamples * 2, 256, 4096))
        {
            SingleReader = true,
            SingleWriter = true,
            FullMode     = BoundedChannelFullMode.Wait,
        });
        var connectionReady = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var streamErrors = new ConcurrentQueue<string>();
        string? firstTaskId = null;
        string? lastTaskId  = null;

        await using var client = MacCoreClient.Create(
            MacCoreClientOptions.CreateDefault(options.BaseUri, token));
        for (var index = 0; index < options.RestSamples; index++)
        {
            var started = Stopwatch.GetTimestamp();
            var health  = await client.GetHealthAsync(cancellationToken).ConfigureAwait(false);
            healthLatency.Add(Stopwatch.GetElapsedTime(started).TotalMilliseconds);
            if (!string.Equals(health.Status, "ok", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException($"Mac Core 健康状态为 {health.Status}。");
            }
        }

        await using var eventStream = new EventStreamClient(
            options.BaseUri,
            token,
            channelCapacity: 2048,
            pongTimeout: TimeSpan.FromSeconds(2),
            pingInterval: TimeSpan.FromMilliseconds(50));
        eventStream.ConnectionStateChanged += (_, state) =>
        {
            if (state == ConnectionState.Online)
            {
                connectionReady.TrySetResult(true);
            }
        };
        eventStream.SocketMeasured += (_, measurement) =>
            socketLatency.Add(measurement.DurationMilliseconds);

        using var streamCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var streamTask = Task.Run(async () =>
        {
            try
            {
                await eventStream.RunAsync(
                    async (envelope, tokenForEvent) =>
                    {
                        if (envelope.TryGetTask(JsonOptions, out var task) && task is not null)
                        {
                            await taskEvents.Writer.WriteAsync(task, tokenForEvent)
                                .ConfigureAwait(false);
                        }
                    },
                    streamCancellation.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (streamCancellation.IsCancellationRequested)
            {
                // 验收结束时主动关闭事件流属于正常控制流。
            }
            catch (Exception exception)
            {
                streamErrors.Enqueue($"{exception.GetType().Name}: {exception.Message}");
                connectionReady.TrySetException(exception);
            }
            finally
            {
                taskEvents.Writer.TryComplete();
            }
        }, CancellationToken.None);

        try
        {
            await connectionReady.Task.WaitAsync(options.ConnectTimeout, cancellationToken)
                .ConfigureAwait(false);
            for (var index = 0; index < options.TaskSamples; index++)
            {
                var endToEndStarted = Stopwatch.GetTimestamp();
                var submitStarted   = Stopwatch.GetTimestamp();
                var task = await client.CreateTaskAsync(
                    new TaskCreateRequest(
                        "phase2.link.acceptance",
                        new Dictionary<string, object?>
                        {
                            ["source"]       = "phase2-windows-diagnostics",
                            ["machine"]      = Environment.MachineName,
                            ["sample_index"] = index,
                            ["created_at"]   = DateTimeOffset.UtcNow,
                        },
                        ResourceTag: "phase2-diagnostic"),
                    $"phase2-diagnostic-{Environment.MachineName}-{Guid.NewGuid():N}",
                    cancellationToken).ConfigureAwait(false);
                taskSubmitLatency.Add(
                    Stopwatch.GetElapsedTime(submitStarted).TotalMilliseconds);
                firstTaskId ??= task.TaskId;
                lastTaskId    = task.TaskId;

                var eventMilliseconds = await WaitForTaskEventAsync(
                    task.TaskId,
                    endToEndStarted,
                    taskEvents.Reader,
                    options.EventTimeout,
                    cancellationToken).ConfigureAwait(false);
                taskEventLatency.Add(eventMilliseconds);
            }

            await WaitForSocketSamplesAsync(
                socketLatency,
                options.SocketSamples,
                options.SocketTimeout,
                cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            streamCancellation.Cancel();
            await IgnoreCancellationAsync(streamTask).ConfigureAwait(false);
        }

        var metrics = new Dictionary<string, MetricResult>(StringComparer.Ordinal)
        {
            ["rest_health"]    = MetricResult.From(healthLatency.Snapshot(), 50, 100),
            ["task_submit"]    = MetricResult.From(taskSubmitLatency.Snapshot(), 80, 150),
            ["task_event"]     = MetricResult.From(taskEventLatency.Snapshot(), 150, 300),
            ["websocket_ping"] = MetricResult.From(socketLatency.Snapshot(), 50, 120),
        };
        var passed = metrics.Values.All(metric => metric.Passed)
            && metrics["rest_health"].Count == options.RestSamples
            && metrics["task_submit"].Count == options.TaskSamples
            && metrics["task_event"].Count == options.TaskSamples
            && metrics["websocket_ping"].Count >= options.SocketSamples
            && streamErrors.IsEmpty;

        return new DiagnosticReport(
            SchemaVersion: "2.2.0",
            GeneratedAt: DateTimeOffset.UtcNow,
            Status: passed ? "pass" : "fail",
            Environment: DiagnosticEnvironment.From(options),
            Metrics: metrics,
            LastSequence: eventStream.LastSequence,
            SampleTaskFirstId: firstTaskId,
            SampleTaskLastId: lastTaskId,
            Errors: streamErrors.ToArray());
    }

    private static async Task<double> WaitForTaskEventAsync(
        string taskId,
        long started,
        ChannelReader<TaskRecord> reader,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutSource.CancelAfter(timeout);
        await foreach (var task in reader.ReadAllAsync(timeoutSource.Token).ConfigureAwait(false))
        {
            if (string.Equals(task.TaskId, taskId, StringComparison.Ordinal))
            {
                return Stopwatch.GetElapsedTime(started).TotalMilliseconds;
            }
        }
        throw new TimeoutException("未在限定时间内收到对应任务事件。");
    }

    private static async Task WaitForSocketSamplesAsync(
        LatencyRecorder recorder,
        int expected,
        TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        var started = Stopwatch.GetTimestamp();
        while (recorder.Snapshot().Count < expected)
        {
            if (Stopwatch.GetElapsedTime(started) >= timeout)
            {
                throw new TimeoutException("WebSocket Ping/Pong 样本数量不足。");
            }
            await Task.Delay(50, cancellationToken).ConfigureAwait(false);
        }
    }

    private static async Task IgnoreCancellationAsync(Task task)
    {
        try
        {
            await task.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // 诊断器完成后主动取消事件流属于正常控制流。
        }
    }

    private static async Task<int> WriteReportAsync(string path, DiagnosticReport report)
    {
        await using var stream = File.Create(path);
        await JsonSerializer.SerializeAsync(stream, report, JsonOptions).ConfigureAwait(false);
        Console.WriteLine(path);
        return string.Equals(report.Status, "pass", StringComparison.Ordinal) ? 0 : 2;
    }
}

/// <summary>诊断程序命令行参数。</summary>
internal sealed record DiagnosticOptions(
    Uri BaseUri,
    string OutputPath,
    int RestSamples,
    int TaskSamples,
    int SocketSamples,
    TimeSpan ConnectTimeout,
    TimeSpan EventTimeout,
    TimeSpan SocketTimeout,
    TimeSpan TotalTimeout)
{
    public static DiagnosticOptions Parse(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index + 1 < args.Length; index += 2)
        {
            values[args[index]] = args[index + 1];
        }
        var baseUrl = values.GetValueOrDefault("--base-url", "http://192.168.1.161:8766");
        var output = values.GetValueOrDefault(
            "--output",
            Path.Combine(Path.GetTempPath(), "phase2-windows-verification.json"));
        var restSamples   = ParsePositive(values, "--rest-samples", 500);
        var taskSamples   = ParsePositive(values, "--task-samples", 500);
        var socketSamples = ParsePositive(values, "--socket-samples", 500);
        var estimatedSeconds = Math.Max(
            900,
            restSamples / 5 + taskSamples * 2 + socketSamples / 10 + 60);
        return new DiagnosticOptions(
            new Uri(baseUrl, UriKind.Absolute),
            output,
            restSamples,
            taskSamples,
            socketSamples,
            TimeSpan.FromSeconds(5),
            TimeSpan.FromSeconds(10),
            TimeSpan.FromSeconds(Math.Max(60, socketSamples / 10 + 30)),
            TimeSpan.FromSeconds(estimatedSeconds));
    }

    private static int ParsePositive(
        Dictionary<string, string> values,
        string key,
        int fallback) =>
        values.TryGetValue(key, out var raw) && int.TryParse(raw, out var value) && value > 0
            ? value
            : fallback;
}

/// <summary>性能报告中的实机环境，不包含设备令牌或业务路径。</summary>
internal sealed record DiagnosticEnvironment(
    [property: JsonPropertyName("machine")] string Machine,
    [property: JsonPropertyName("operating_system")] string OperatingSystem,
    [property: JsonPropertyName("architecture")] string Architecture,
    [property: JsonPropertyName("base_url")] string BaseUrl,
    [property: JsonPropertyName("rest_samples")] int RestSamples,
    [property: JsonPropertyName("task_samples")] int TaskSamples,
    [property: JsonPropertyName("socket_samples")] int SocketSamples)
{
    public static DiagnosticEnvironment From(DiagnosticOptions options) => new(
        Environment.MachineName,
        RuntimeInformation.OSDescription,
        RuntimeInformation.OSArchitecture.ToString(),
        options.BaseUri.ToString(),
        options.RestSamples,
        options.TaskSamples,
        options.SocketSamples);
}

/// <summary>单项分位数及其验收阈值。</summary>
internal sealed record MetricResult(
    [property: JsonPropertyName("count")] int Count,
    [property: JsonPropertyName("p50_ms")] double P50Milliseconds,
    [property: JsonPropertyName("p95_ms")] double P95Milliseconds,
    [property: JsonPropertyName("p99_ms")] double P99Milliseconds,
    [property: JsonPropertyName("max_ms")] double MaximumMilliseconds,
    [property: JsonPropertyName("p95_limit_ms")] double P95LimitMilliseconds,
    [property: JsonPropertyName("p99_limit_ms")] double P99LimitMilliseconds,
    [property: JsonPropertyName("passed")] bool Passed)
{
    public static MetricResult From(
        LatencySummary summary,
        double p95Limit,
        double p99Limit) => new(
        summary.Count,
        summary.P50Milliseconds,
        summary.P95Milliseconds,
        summary.P99Milliseconds,
        summary.MaximumMilliseconds,
        p95Limit,
        p99Limit,
        summary.Count > 0
            && summary.P95Milliseconds <= p95Limit
            && summary.P99Milliseconds <= p99Limit);
}

/// <summary>符合 performance_report_v2.schema.json 的 Phase 2 实机验收报告。</summary>
internal sealed record DiagnosticReport(
    [property: JsonPropertyName("schema_version")] string SchemaVersion,
    [property: JsonPropertyName("generated_at")] DateTimeOffset GeneratedAt,
    [property: JsonPropertyName("status")] string Status,
    [property: JsonPropertyName("environment")] DiagnosticEnvironment Environment,
    [property: JsonPropertyName("metrics")] IReadOnlyDictionary<string, MetricResult> Metrics,
    [property: JsonPropertyName("last_sequence")] long? LastSequence,
    [property: JsonPropertyName("sample_task_first_id")] string? SampleTaskFirstId,
    [property: JsonPropertyName("sample_task_last_id")] string? SampleTaskLastId,
    [property: JsonPropertyName("errors")] IReadOnlyList<string> Errors)
{
    public static DiagnosticReport Incomplete(
        DiagnosticOptions options,
        string message) => new(
        "2.2.0",
        DateTimeOffset.UtcNow,
        "incomplete",
        DiagnosticEnvironment.From(options),
        new Dictionary<string, MetricResult>(),
        null,
        null,
        null,
        new[] { message });

    public static DiagnosticReport Failed(
        DiagnosticOptions options,
        string code,
        string type,
        string message) => new(
        "2.2.0",
        DateTimeOffset.UtcNow,
        "fail",
        DiagnosticEnvironment.From(options),
        new Dictionary<string, MetricResult>(),
        null,
        null,
        null,
        new[] { $"{code} | {type}: {message}" });
}
