namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>不依赖墙钟或 Random 的确定性眨眼调度；同一 seed 与 dt 序列始终得到相同眼睑节奏。</summary>
internal static class MaotaiNaturalBlink
{
    private const double CycleSeconds = 12.0;
    private const double BlinkSeconds = 0.18;
    private const double HalfCloseEnd = 0.045;
    private const double FullCloseEnd = 0.115;

    /// <summary>只修饰原本为 Open 的基础眼态；Offline/Error/疲劳/哈欠等强表情永远保持原值。</summary>
    public static MaotaiEyeState Resolve(
        MaotaiEyeState baseState,
        double elapsedSeconds,
        double seedPhaseRadians)
    {
        if (baseState != MaotaiEyeState.Open ||
            !double.IsFinite(elapsedSeconds) ||
            !double.IsFinite(seedPhaseRadians))
        {
            return baseState;
        }

        var seedOffset = (seedPhaseRadians / (Math.PI * 2.0)) * 1.35;
        var cycleTime  = Wrap(elapsedSeconds + seedOffset, CycleSeconds);

        var localBlinkTime = GetBlinkLocalTime(cycleTime);
        if (localBlinkTime < 0.0 || localBlinkTime >= BlinkSeconds)
        {
            return MaotaiEyeState.Open;
        }

        if (localBlinkTime < HalfCloseEnd || localBlinkTime >= FullCloseEnd)
        {
            return MaotaiEyeState.Half;
        }

        return MaotaiEyeState.Closed;
    }

    private static double GetBlinkLocalTime(double cycleTime)
    {
        // Three deliberately uneven gaps avoid a metronomic blink cadence while staying deterministic.
        var first  = cycleTime - 2.45;
        var second = cycleTime - 7.05;
        var third  = cycleTime - 10.75;

        if (first >= 0.0 && first < BlinkSeconds)
        {
            return first;
        }
        if (second >= 0.0 && second < BlinkSeconds)
        {
            return second;
        }
        if (third >= 0.0 && third < BlinkSeconds)
        {
            return third;
        }

        return -1.0;
    }

    private static double Wrap(double value, double period)
    {
        value %= period;
        return value < 0.0
            ? value + period
            : value;
    }
}
