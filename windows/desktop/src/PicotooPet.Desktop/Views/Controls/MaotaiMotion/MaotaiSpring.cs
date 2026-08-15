namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>用于头、耳、尾等次级运动的稳定二阶阻尼弹簧。</summary>
internal sealed class MaotaiSpring
{
    private const double MaximumStepSeconds = 1.0 / 240.0;

    private readonly double _frequencyHz;
    private readonly double _dampingRatio;

    public MaotaiSpring(
        double value,
        double velocity,
        double frequencyHz,
        double dampingRatio)
    {
        if (!double.IsFinite(value) || !double.IsFinite(velocity))
        {
            throw new ArgumentOutOfRangeException(nameof(value));
        }
        if (!double.IsFinite(frequencyHz) || frequencyHz <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(frequencyHz));
        }
        if (!double.IsFinite(dampingRatio) || dampingRatio < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(dampingRatio));
        }

        Value         = value;
        Velocity      = velocity;
        _frequencyHz  = frequencyHz;
        _dampingRatio = dampingRatio;
    }

    public double Value { get; private set; }

    public double Velocity { get; private set; }

    /// <summary>按时间推进到目标值；长帧被裁剪并细分，避免数值爆炸和补帧瞬移。</summary>
    public void Step(double target, double deltaTime)
    {
        if (!double.IsFinite(target) || !double.IsFinite(deltaTime))
        {
            return;
        }

        var clampedDelta = Math.Clamp(deltaTime, 0.0, 0.05);
        if (clampedDelta <= 0)
        {
            return;
        }

        var substepCount = Math.Max(
            1,
            (int)Math.Ceiling(clampedDelta / MaximumStepSeconds));
        var stepSeconds = clampedDelta / substepCount;
        var omega       = 2.0 * Math.PI * _frequencyHz;
        var stiffness   = omega * omega;
        var damping     = 2.0 * _dampingRatio * omega;

        for (var index = 0; index < substepCount; index++)
        {
            var acceleration = (stiffness * (target - Value)) - (damping * Velocity);
            Velocity        += acceleration * stepSeconds;
            Value           += Velocity * stepSeconds;
        }
    }

    /// <summary>在状态切换/重新挂载时同步重置位置和速度。</summary>
    public void Reset(double value, double velocity = 0)
    {
        Value    = double.IsFinite(value) ? value : 0;
        Velocity = double.IsFinite(velocity) ? velocity : 0;
    }
}
