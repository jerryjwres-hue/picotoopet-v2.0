namespace PicotooPet.Desktop.Core.Networking;

/// <summary>具有上限与随机抖动的指数重连策略。</summary>
public sealed class ReconnectPolicy
{
    private readonly TimeSpan _minimum;
    private readonly TimeSpan _maximum;
    private readonly int _jitterMilliseconds;

    /// <summary>创建默认策略；首轮重连保持在 500 ms 以内。</summary>
    public ReconnectPolicy(
        TimeSpan? minimum = null,
        TimeSpan? maximum = null,
        int jitterMilliseconds = 100)
    {
        _minimum            = minimum ?? TimeSpan.FromMilliseconds(200);
        _maximum            = maximum ?? TimeSpan.FromSeconds(5);
        _jitterMilliseconds = Math.Max(0, jitterMilliseconds);
    }

    /// <summary>根据连续失败次数计算下一次等待。</summary>
    public TimeSpan GetDelay(int attempt)
    {
        var boundedAttempt = Math.Clamp(attempt, 0, 8);
        var exponential    = _minimum.TotalMilliseconds * Math.Pow(2, boundedAttempt);
        var capped         = Math.Min(exponential, _maximum.TotalMilliseconds);
        var jitter         = _jitterMilliseconds == 0
            ? 0
            : Random.Shared.Next(0, _jitterMilliseconds + 1);
        return TimeSpan.FromMilliseconds(capped + jitter);
    }
}
