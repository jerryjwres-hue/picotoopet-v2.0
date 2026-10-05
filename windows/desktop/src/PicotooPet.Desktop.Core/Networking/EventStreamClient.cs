using System.Buffers;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading.Channels;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>支持事件续传、有界背压、Ping/Pong 和自动重连的 WebSocket 客户端。</summary>
public sealed class EventStreamClient : IEventStreamSession
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly Uri _baseUri;
    private readonly string _token;
    private readonly ReconnectPolicy _reconnectPolicy;
    private readonly TimeSpan _pongTimeout;
    private readonly TimeSpan _pingInterval;
    private readonly Channel<EventEnvelope> _channel;
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private readonly ConcurrentDictionary<string, long> _pendingPings = new();
    private long _lastSequence;

    /// <summary>连接状态发生变化时通知桌面状态层。</summary>
    public event EventHandler<ConnectionState>? ConnectionStateChanged;

    /// <summary>收到 Ping/Pong 往返样本时通知性能层。</summary>
    public event EventHandler<SocketMeasurement>? SocketMeasured;

    /// <summary>创建有界事件流客户端。</summary>
    public EventStreamClient(
        Uri baseUri,
        string token,
        long lastSequence = 0,
        int channelCapacity = 512,
        ReconnectPolicy? reconnectPolicy = null,
        TimeSpan? pongTimeout = null,
        TimeSpan? pingInterval = null)
    {
        _baseUri         = baseUri;
        _token           = token;
        _lastSequence    = Math.Max(0, lastSequence);
        _reconnectPolicy = reconnectPolicy ?? new ReconnectPolicy();
        _pongTimeout     = pongTimeout ?? TimeSpan.FromSeconds(30);
        _pingInterval    = pingInterval ?? TimeSpan.FromSeconds(10);
        if (_pongTimeout <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(pongTimeout), "Pong 超时必须大于零。");
        }
        if (_pingInterval <= TimeSpan.Zero || _pingInterval >= _pongTimeout)
        {
            throw new ArgumentOutOfRangeException(
                nameof(pingInterval),
                "Ping 间隔必须大于零且小于 Pong 超时。");
        }
        _channel = Channel.CreateBounded<EventEnvelope>(
            new BoundedChannelOptions(Math.Max(16, channelCapacity))
            {
                SingleReader = true,
                SingleWriter = true,
                FullMode     = BoundedChannelFullMode.Wait,
            });
    }

    /// <summary>最后一个已被状态层成功消费的持久事件序号。</summary>
    public long LastSequence => Interlocked.Read(ref _lastSequence);

    /// <summary>持续连接并把已确认事件交给单线程状态归并器。</summary>
    public async Task RunAsync(
        Func<EventEnvelope, CancellationToken, ValueTask> consume,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(consume);
        var consumer = ConsumeAsync(consume, cancellationToken);
        try
        {
            await ReconnectLoopAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _channel.Writer.TryComplete();
            await consumer.ConfigureAwait(false);
            PublishState(ConnectionState.Offline);
        }
    }

    private async Task ReconnectLoopAsync(CancellationToken cancellationToken)
    {
        var attempt = 0;
        while (!cancellationToken.IsCancellationRequested)
        {
            PublishState(attempt == 0 ? ConnectionState.Connecting : ConnectionState.Reconnecting);
            using var socket = new ClientWebSocket();
            socket.Options.SetRequestHeader("Authorization", $"Bearer {_token}");
            socket.Options.KeepAliveInterval = TimeSpan.FromSeconds(30);
            try
            {
                await socket.ConnectAsync(BuildEventUri(), cancellationToken).ConfigureAwait(false);
                PublishState(ConnectionState.Online);
                attempt = 0;
                await RunConnectedAsync(socket, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception) when (IsAuthenticationFailure(exception))
            {
                PublishState(ConnectionState.AuthenticationFailed);
                throw new EventStreamAuthenticationException(
                    "Mac Core 拒绝了 WebSocket 设备认证。",
                    exception);
            }
            catch (Exception) when (!cancellationToken.IsCancellationRequested)
            {
                PublishState(ConnectionState.Reconnecting);
                var delay = _reconnectPolicy.GetDelay(attempt++);
                await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
            }
        }
    }

    private async Task RunConnectedAsync(
        ClientWebSocket socket,
        CancellationToken cancellationToken)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var receiveTask  = ReceiveLoopAsync(socket, linked.Token);
        var pingTask     = PingLoopAsync(socket, linked.Token);
        var completed = await Task.WhenAny(receiveTask, pingTask).ConfigureAwait(false);
        try
        {
            await completed.ConfigureAwait(false);
        }
        finally
        {
            linked.Cancel();
            await Task.WhenAll(
                IgnoreCompletionAsync(receiveTask),
                IgnoreCompletionAsync(pingTask)).ConfigureAwait(false);
            _pendingPings.Clear();
        }
    }

    private async Task ReceiveLoopAsync(
        ClientWebSocket socket,
        CancellationToken cancellationToken)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(64 * 1024);
        try
        {
            while (!cancellationToken.IsCancellationRequested)
            {
                using var message = new MemoryStream();
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(
                        new ArraySegment<byte>(buffer),
                        cancellationToken).ConfigureAwait(false);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return;
                    }
                    message.Write(buffer, 0, result.Count);
                }
                while (!result.EndOfMessage);

                if (result.MessageType != WebSocketMessageType.Text)
                {
                    continue;
                }
                await ProcessMessageAsync(message.ToArray(), cancellationToken).ConfigureAwait(false);
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private async Task ProcessMessageAsync(byte[] utf8Json, CancellationToken cancellationToken)
    {
        using var document = JsonDocument.Parse(utf8Json);
        var root = document.RootElement;
        if (root.TryGetProperty("type", out var type) && type.GetString() == "pong")
        {
            var nonce = root.TryGetProperty("nonce", out var nonceElement)
                ? nonceElement.GetString()
                : null;
            if (nonce is not null && _pendingPings.TryRemove(nonce, out var started))
            {
                var elapsed = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
                SocketMeasured?.Invoke(this, new SocketMeasurement(elapsed, nonce));
            }
            RecordInboundActivity();
            return;
        }

        // ── Any valid inbound application message proves the transport is alive. ──
        RecordInboundActivity();
        if (root.TryGetProperty("topic", out var topic) && topic.GetString() == "connected")
        {
            return;
        }

        var envelope = root.Deserialize<EventEnvelope>(JsonOptions);
        if (envelope is null || envelope.Sequence <= LastSequence)
        {
            return;
        }
        await _channel.Writer.WriteAsync(envelope, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// 有效入站业务消息比单个延迟应用层 Pong 更强，因此丢弃旧 Ping 延迟样本，
    /// 防止服务端事件发送锁或历史重放把健康连接误判为半连接。
    /// </summary>
    private void RecordInboundActivity() => _pendingPings.Clear();

    private async Task PingLoopAsync(
        ClientWebSocket socket,
        CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            if (DeferPingWhileEventsPending())
            {
                await Task.Delay(_pingInterval, cancellationToken).ConfigureAwait(false);
                continue;
            }

            ThrowIfPongExpired();
            var nonce   = Guid.NewGuid().ToString("N");
            var started = Stopwatch.GetTimestamp();
            _pendingPings[nonce] = started;
            var payload = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new
            {
                type = "ping",
                nonce,
            }));

            await _sendLock.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                await socket.SendAsync(
                    new ArraySegment<byte>(payload),
                    WebSocketMessageType.Text,
                    endOfMessage: true,
                    cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                _sendLock.Release();
            }
            await Task.Delay(_pingInterval, cancellationToken).ConfigureAwait(false);
        }
    }

    private void ThrowIfPongExpired()
    {
        if (DeferPingWhileEventsPending())
        {
            return;
        }

        // 只有持续超过 deadline 且期间没有更近的有效入站消息时，才把连接视为半连接。
        foreach (var pending in _pendingPings)
        {
            if (Stopwatch.GetElapsedTime(pending.Value) < _pongTimeout)
            {
                continue;
            }
            throw new TimeoutException(
                $"WebSocket Pong 超时：{_pongTimeout.TotalMilliseconds:F0} ms。" );
        }
    }

    private bool DeferPingWhileEventsPending()
    {
        if (!_channel.Reader.CanCount || _channel.Reader.Count == 0)
        {
            return false;
        }

        // 冷启动重放期间 Pong 可能排在历史事件之后；旧 Ping 已不再代表可用延迟样本。
        _pendingPings.Clear();
        return true;
    }

    private async Task ConsumeAsync(
        Func<EventEnvelope, CancellationToken, ValueTask> consume,
        CancellationToken cancellationToken)
    {
        await foreach (var envelope in _channel.Reader.ReadAllAsync(cancellationToken)
                           .ConfigureAwait(false))
        {
            if (envelope.Sequence <= LastSequence)
            {
                continue;
            }
            await consume(envelope, cancellationToken).ConfigureAwait(false);
            Interlocked.Exchange(ref _lastSequence, envelope.Sequence);
        }
    }

    private Uri BuildEventUri()
    {
        var builder = new UriBuilder(_baseUri)
        {
            Scheme = _baseUri.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase)
                ? "wss"
                : "ws",
            Path  = "/api/v1/events",
            Query = $"after_sequence={LastSequence}",
        };
        return builder.Uri;
    }

    private static async Task IgnoreCompletionAsync(Task task)
    {
        try
        {
            await task.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // 连接切换时取消配套收发任务属于正常控制流。
        }
        catch (WebSocketException)
        {
            // 主任务已经保留原始断线异常，清理配套任务时不重复覆盖。
        }
    }

    private static bool IsAuthenticationFailure(Exception exception)
    {
        for (var current = exception; current is not null; current = current.InnerException)
        {
            if (current is HttpRequestException
                { StatusCode: HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden })
            {
                return true;
            }
        }
        return exception is WebSocketException
        { WebSocketErrorCode: WebSocketError.HeaderError };
    }

    private void PublishState(ConnectionState state) =>
        ConnectionStateChanged?.Invoke(this, state);

    /// <summary>释放发送锁；Socket 本身按连接周期及时释放。</summary>
    public ValueTask DisposeAsync()
    {
        _pendingPings.Clear();
        _sendLock.Dispose();
        return ValueTask.CompletedTask;
    }
}

/// <summary>WebSocket 握手因设备令牌被拒绝而失败。</summary>
public sealed class EventStreamAuthenticationException : Exception
{
    public EventStreamAuthenticationException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
