namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>只描述休息状态下的自主表现意图；不写 Core/Worker/Task/Approval。</summary>
internal enum MaotaiAutonomousBehavior
{
    Idle,
    Wander,
    Run,
    Sit,
    LieDown,
}

/// <summary>自主调度器输出的纯值意图；真正的骨骼运动仍由同一个 Motion Engine 生成。</summary>
internal readonly record struct MaotaiAutonomousIntent(
    double TargetX,
    bool WantsRun,
    MaotaiMotionState? AutonomousState,
    MaotaiAutonomousBehavior Behavior,
    int Sequence);

/// <summary>
/// 有记忆的确定性自主行为调度器。每个行为都有退出时间，连续选择禁止重复；
/// 用户交互或强状态到来时只暂停/清空当前意图，不建立第二套业务状态机。
/// </summary>
internal sealed class MaotaiAutonomousBehaviorController
{
    private uint _randomState;
    private bool _hasActiveIntent;
    private double _remainingSeconds;
    private double _targetX;
    private MaotaiAutonomousBehavior _behavior = MaotaiAutonomousBehavior.Idle;
    private MaotaiAutonomousBehavior? _lastSelectedBehavior;
    private int _sequence;

    public MaotaiAutonomousBehaviorController(int seed)
    {
        _randomState = unchecked((uint)seed);
        if (_randomState == 0)
        {
            _randomState = 0x9E3779B9u;
        }
    }

    /// <summary>
    /// 推进自主选择；相同 seed 与输入序列得到相同结果。所有持续时间都严格小于五秒，
    /// 让真实状态/用户操作能快速重新取得控制权。
    /// </summary>
    public MaotaiAutonomousIntent Update(
        double deltaTime,
        double currentX,
        double minX,
        double maxX,
        bool floatingMode,
        bool enabled)
    {
        NormalizeBounds(ref minX, ref maxX);
        currentX = double.IsFinite(currentX)
            ? Math.Clamp(currentX, minX, maxX)
            : (minX + maxX) * 0.5;

        if (!enabled)
        {
            _hasActiveIntent = false;
            _remainingSeconds = 0.0;
            _targetX = currentX;
            return new MaotaiAutonomousIntent(
                currentX,
                WantsRun: false,
                AutonomousState: null,
                MaotaiAutonomousBehavior.Idle,
                _sequence);
        }

        var dt = double.IsFinite(deltaTime)
            ? Math.Clamp(deltaTime, 0.0, 0.05)
            : 0.0;

        if (_hasActiveIntent)
        {
            _remainingSeconds = Math.Max(0.0, _remainingSeconds - dt);
        }

        if (!_hasActiveIntent || _remainingSeconds <= 0.0)
        {
            SelectNext(currentX, minX, maxX, floatingMode);
        }

        var autonomousState = _behavior switch
        {
            MaotaiAutonomousBehavior.Sit     => MaotaiMotionState.Sit,
            MaotaiAutonomousBehavior.LieDown => MaotaiMotionState.LieDown,
            _                                => (MaotaiMotionState?)null,
        };

        return new MaotaiAutonomousIntent(
            _targetX,
            WantsRun: _behavior == MaotaiAutonomousBehavior.Run,
            autonomousState,
            _behavior,
            _sequence);
    }

    private void SelectNext(
        double currentX,
        double minX,
        double maxX,
        bool floatingMode)
    {
        var next = PickWeightedBehavior(floatingMode);
        if (_lastSelectedBehavior == next)
        {
            // One deterministic reroll is enough for natural weighting; fallback guarantees the Cooldown invariant.
            next = PickWeightedBehavior(floatingMode);
            if (_lastSelectedBehavior == next)
            {
                next = NextDifferentBehavior(next, floatingMode);
            }
        }

        _behavior = next;
        _lastSelectedBehavior = next;
        _sequence++;
        _hasActiveIntent = true;

        switch (next)
        {
            case MaotaiAutonomousBehavior.Wander:
                _targetX = PickTravelTarget(currentX, minX, maxX, minimumTravel: 12.0);
                _remainingSeconds = Lerp(1.8, 3.5, NextUnit());
                break;

            case MaotaiAutonomousBehavior.Run:
                _targetX = PickTravelTarget(currentX, minX, maxX, minimumTravel: 24.0);
                _remainingSeconds = Lerp(1.2, 2.3, NextUnit());
                break;

            case MaotaiAutonomousBehavior.Sit:
                _targetX = currentX;
                _remainingSeconds = Lerp(1.5, 3.2, NextUnit());
                break;

            case MaotaiAutonomousBehavior.LieDown:
                _targetX = currentX;
                _remainingSeconds = Lerp(2.0, 4.2, NextUnit());
                break;

            default:
                _targetX = currentX;
                _remainingSeconds = Lerp(1.0, 2.2, NextUnit());
                break;
        }
    }

    private MaotaiAutonomousBehavior PickWeightedBehavior(bool floatingMode)
    {
        var roll = NextUnit() * 100.0;
        if (floatingMode)
        {
            if (roll < 18.0) return MaotaiAutonomousBehavior.Idle;
            if (roll < 53.0) return MaotaiAutonomousBehavior.Wander;
            if (roll < 73.0) return MaotaiAutonomousBehavior.Run;
            if (roll < 87.0) return MaotaiAutonomousBehavior.Sit;
            return MaotaiAutonomousBehavior.LieDown;
        }

        if (roll < 25.0) return MaotaiAutonomousBehavior.Idle;
        if (roll < 65.0) return MaotaiAutonomousBehavior.Wander;
        if (roll < 85.0) return MaotaiAutonomousBehavior.Sit;
        return MaotaiAutonomousBehavior.LieDown;
    }

    private static MaotaiAutonomousBehavior NextDifferentBehavior(
        MaotaiAutonomousBehavior previous,
        bool floatingMode)
    {
        if (!floatingMode && previous == MaotaiAutonomousBehavior.Wander)
        {
            return MaotaiAutonomousBehavior.Sit;
        }

        return previous switch
        {
            MaotaiAutonomousBehavior.Idle    => MaotaiAutonomousBehavior.Wander,
            MaotaiAutonomousBehavior.Wander  => floatingMode
                ? MaotaiAutonomousBehavior.Run
                : MaotaiAutonomousBehavior.Sit,
            MaotaiAutonomousBehavior.Run     => MaotaiAutonomousBehavior.Sit,
            MaotaiAutonomousBehavior.Sit     => MaotaiAutonomousBehavior.LieDown,
            _                                => MaotaiAutonomousBehavior.Idle,
        };
    }

    private double PickTravelTarget(
        double currentX,
        double minX,
        double maxX,
        double minimumTravel)
    {
        var span = maxX - minX;
        if (span <= 2.0)
        {
            return currentX;
        }

        var margin = Math.Min(8.0, span * 0.12);
        var safeMin = minX + margin;
        var safeMax = maxX - margin;
        if (safeMin > safeMax)
        {
            safeMin = minX;
            safeMax = maxX;
        }

        var candidate = Lerp(safeMin, safeMax, NextUnit());
        var required = Math.Min(minimumTravel, (safeMax - safeMin) * 0.45);
        if (Math.Abs(candidate - currentX) < required)
        {
            var leftRoom = currentX - safeMin;
            var rightRoom = safeMax - currentX;
            candidate = rightRoom >= leftRoom
                ? Math.Min(safeMax, currentX + required)
                : Math.Max(safeMin, currentX - required);
        }

        return Math.Clamp(candidate, minX, maxX);
    }

    private double NextUnit()
    {
        var value = _randomState;
        value ^= value << 13;
        value ^= value >> 17;
        value ^= value << 5;
        _randomState = value == 0 ? 0xA341316Cu : value;
        return (_randomState & 0x00FFFFFFu) / 16777216.0;
    }

    private static void NormalizeBounds(ref double minX, ref double maxX)
    {
        if (!double.IsFinite(minX)) minX = 0.0;
        if (!double.IsFinite(maxX)) maxX = minX;
        if (minX > maxX)
        {
            (minX, maxX) = (maxX, minX);
        }
    }

    private static double Lerp(double from, double to, double t) =>
        from + ((to - from) * Math.Clamp(t, 0.0, 1.0));
}
