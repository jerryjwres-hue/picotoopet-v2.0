namespace PicotooPet.Desktop.Core.State;

/// <summary>固定容量、线程安全的延迟分位数记录器。</summary>
public sealed class LatencyRecorder
{
    private readonly object _gate = new();
    private readonly Queue<double> _samples;
    private readonly int _capacity;

    /// <summary>创建固定容量样本环，避免长时间运行无限增长。</summary>
    public LatencyRecorder(int capacity = 4096)
    {
        _capacity = Math.Max(32, capacity);
        _samples  = new Queue<double>(_capacity);
    }

    /// <summary>追加非负毫秒样本。</summary>
    public void Add(double milliseconds)
    {
        if (milliseconds < 0 || double.IsNaN(milliseconds) || double.IsInfinity(milliseconds))
        {
            throw new ArgumentOutOfRangeException(nameof(milliseconds));
        }

        lock (_gate)
        {
            if (_samples.Count == _capacity)
            {
                _samples.Dequeue();
            }
            _samples.Enqueue(milliseconds);
        }
    }

    /// <summary>按最近秩生成 count、p50、p95、p99 和最大值。</summary>
    public LatencySummary Snapshot()
    {
        double[] ordered;
        lock (_gate)
        {
            ordered = _samples.Order().ToArray();
        }
        if (ordered.Length == 0)
        {
            return LatencySummary.Empty;
        }
        return new LatencySummary(
            ordered.Length,
            Percentile(ordered, 0.50),
            Percentile(ordered, 0.95),
            Percentile(ordered, 0.99),
            Math.Round(ordered[^1], 3));
    }

    private static double Percentile(double[] ordered, double percentile)
    {
        var rank = Math.Max(1, (int)Math.Ceiling(percentile * ordered.Length));
        return Math.Round(ordered[rank - 1], 3);
    }
}

/// <summary>桌面端展示和导出使用的延迟摘要。</summary>
public sealed record LatencySummary(
    int Count,
    double P50Milliseconds,
    double P95Milliseconds,
    double P99Milliseconds,
    double MaximumMilliseconds)
{
    public static LatencySummary Empty { get; } = new(0, 0, 0, 0, 0);
}
