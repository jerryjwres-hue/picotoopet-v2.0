using System.Text;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Core.Logging;

/// <summary>自动遮蔽秘密并在后台顺序写盘的有界日志器。</summary>
public sealed partial class SafeFileLogger : IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly object _emergencyGate = new();
    private readonly Queue<string> _pending;
    private readonly SemaphoreSlim _signal = new(0, 1);
    private readonly string _path;
    private readonly string _emergencyPath;
    private readonly int _capacity;
    private readonly Task _writerTask;
    private bool _completed;
    private long _droppedLines;

    /// <summary>创建后台日志器；普通调用只完成脱敏和入队，不执行磁盘 I/O。</summary>
    public SafeFileLogger(string path, int capacity = 4096)
    {
        _path = path;
        _capacity = Math.Max(128, capacity);
        _pending = new Queue<string>(_capacity);
        var directory = Path.GetDirectoryName(path) ?? ".";
        Directory.CreateDirectory(directory);
        var fileName = Path.GetFileNameWithoutExtension(path);
        var extension = Path.GetExtension(path);
        _emergencyPath = Path.Combine(directory, $"{fileName}-fatal{extension}");
        _writerTask = Task.Run(WriterLoopAsync);
    }

    /// <summary>写入脱敏信息。</summary>
    public void Info(string message) => Enqueue("INFO", message);

    /// <summary>写入脱敏错误摘要和异常类型，不写异常数据中的秘密。</summary>
    public void Error(string message, Exception exception) =>
        Enqueue("ERROR", FormatException(message, exception));

    /// <summary>
    /// 为即将终止进程的未知异常同步写一份独立 fatal 证据；仍保留原异步日志，且不吞异常。
    /// </summary>
    public void EmergencyError(string message, Exception exception)
    {
        var summary = FormatException(message, exception);
        Enqueue("ERROR", summary);
        var line = FormatLine("FATAL", summary);
        lock (_emergencyGate)
        {
            try
            {
                using var stream = new FileStream(
                    _emergencyPath,
                    FileMode.Append,
                    FileAccess.Write,
                    FileShare.ReadWrite,
                    bufferSize: 4096,
                    options: FileOptions.WriteThrough);
                using var writer = new StreamWriter(
                    stream,
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                    bufferSize: 4096,
                    leaveOpen: true);
                writer.WriteLine(line);
                writer.Flush();
                stream.Flush(flushToDisk: true);
            }
            catch (IOException)
            {
                // Fatal 路径必须保持 best-effort，不能用日志异常覆盖原始进程级异常。
            }
            catch (UnauthorizedAccessException)
            {
                // 权限异常同样不得改变原来的 fail-fast 语义。
            }
        }
    }

    private void Enqueue(string level, string message)
    {
        var line = FormatLine(level, message);
        var shouldSignal = false;
        lock (_gate)
        {
            if (_completed)
            {
                return;
            }
            if (_pending.Count == _capacity)
            {
                _pending.Dequeue();
                _droppedLines++;
            }
            shouldSignal = _pending.Count == 0;
            _pending.Enqueue(line);
        }
        if (shouldSignal)
        {
            _signal.Release();
        }
    }

    private static string FormatException(string message, Exception exception) =>
        $"{message} | {exception.GetType().Name}: {exception.Message}";

    private static string FormatLine(string level, string message)
    {
        var redacted = TokenPattern().Replace(
            BearerPattern().Replace(message, "Bearer [REDACTED]"),
            "[REDACTED]");
        return $"{DateTimeOffset.UtcNow:O}\t{level}\t{redacted}";
    }

    private async Task WriterLoopAsync()
    {
        await using var stream = new FileStream(
            _path,
            FileMode.Append,
            FileAccess.Write,
            FileShare.ReadWrite,
            bufferSize: 16 * 1024,
            options: FileOptions.Asynchronous | FileOptions.SequentialScan);
        await using var writer = new StreamWriter(
            stream,
            new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
            bufferSize: 16 * 1024,
            leaveOpen: false);

        while (true)
        {
            await _signal.WaitAsync().ConfigureAwait(false);
            var batch = DrainBatch(out var completed, out var droppedLines);
            if (droppedLines > 0)
            {
                await writer.WriteLineAsync(
                    $"{DateTimeOffset.UtcNow:O}\tWARN\t日志队列过载，已覆盖 {droppedLines} 条最旧记录。")
                    .ConfigureAwait(false);
            }
            foreach (var line in batch)
            {
                await writer.WriteLineAsync(line).ConfigureAwait(false);
            }
            await writer.FlushAsync().ConfigureAwait(false);
            if (completed)
            {
                return;
            }
        }
    }

    private List<string> DrainBatch(out bool completed, out long droppedLines)
    {
        var batch = new List<string>();
        lock (_gate)
        {
            while (_pending.Count > 0)
            {
                batch.Add(_pending.Dequeue());
            }
            droppedLines = _droppedLines;
            _droppedLines = 0;
            completed = _completed;
        }
        return batch;
    }

    /// <summary>停止接收新日志，刷新队列并等待后台文件句柄关闭。</summary>
    public async ValueTask DisposeAsync()
    {
        var shouldSignal = false;
        lock (_gate)
        {
            if (_completed)
            {
                return;
            }
            _completed = true;
            shouldSignal = _pending.Count == 0;
        }
        if (shouldSignal)
        {
            _signal.Release();
        }
        await _writerTask.ConfigureAwait(false);
        _signal.Dispose();
    }

    [GeneratedRegex(@"Bearer\s+[A-Za-z0-9._~+/=-]+", RegexOptions.IgnoreCase)]
    private static partial Regex BearerPattern();

    [GeneratedRegex(@"\b[A-Za-z0-9_-]{40,}\b")]
    private static partial Regex TokenPattern();
}