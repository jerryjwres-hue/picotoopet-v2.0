namespace PicotooPet.Desktop.Core.Networking;

/// <summary>按实时通道健康度自适应调度低频 REST 真相对账。</summary>
public sealed class CoreSnapshotPoller
{
    private readonly Func<CancellationToken, Task> _pollSnapshot;
    private readonly Func<bool> _realtimeHealthy;
    private readonly TimeSpan _healthyInterval;
    private readonly TimeSpan _degradedInterval;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;

    /// <summary>创建有界轮询器；健康实时通道降低 REST 频率，降级时提高频率。</summary>
    public CoreSnapshotPoller(
        Func<CancellationToken, Task> pollSnapshot,
        Func<bool> realtimeHealthy,
        TimeSpan? healthyInterval = null,
        TimeSpan? degradedInterval = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _pollSnapshot      = pollSnapshot ?? throw new ArgumentNullException(nameof(pollSnapshot));
        _realtimeHealthy   = realtimeHealthy ?? throw new ArgumentNullException(nameof(realtimeHealthy));
        _healthyInterval   = healthyInterval ?? TimeSpan.FromSeconds(15);
        _degradedInterval  = degradedInterval ?? TimeSpan.FromSeconds(3);
        _delay             = delay ?? Task.Delay;
        if (_healthyInterval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(healthyInterval));
        }
        if (_degradedInterval <= TimeSpan.Zero || _degradedInterval > _healthyInterval)
        {
            throw new ArgumentOutOfRangeException(nameof(degradedInterval));
        }
    }

    /// <summary>持续读取 REST 真相；调用方负责在认证失败或生命周期结束时取消。</summary>
    public async Task RunAsync(CancellationToken cancellationToken)
    {
        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await _pollSnapshot(cancellationToken).ConfigureAwait(false);
            var interval = _realtimeHealthy()
                ? _healthyInterval
                : _degradedInterval;
            await _delay(interval, cancellationToken).ConfigureAwait(false);
        }
    }
}
