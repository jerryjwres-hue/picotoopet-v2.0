using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.State;

namespace PicotooPet.Desktop.Core.Networking;

/// <summary>协调器消费的事件流会话边界；真实 WebSocket 与内存测试共享同一契约。</summary>
public interface IEventStreamSession : IAsyncDisposable
{
    /// <summary>连接状态发生变化时通知状态层。</summary>
    event EventHandler<ConnectionState>? ConnectionStateChanged;

    /// <summary>收到 Ping/Pong 往返样本时通知性能层。</summary>
    event EventHandler<SocketMeasurement>? SocketMeasured;

    /// <summary>持续连接并按顺序交付事件；消费完成后才确认序号。</summary>
    Task RunAsync(
        Func<EventEnvelope, CancellationToken, ValueTask> consume,
        CancellationToken cancellationToken);
}
