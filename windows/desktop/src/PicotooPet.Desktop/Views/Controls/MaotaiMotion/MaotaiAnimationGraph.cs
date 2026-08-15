namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>茅台连续动画图中的逻辑动作节点。</summary>
internal enum MaotaiMotionState
{
    Idle,
    Look,
    Walk,
    Run,
    JumpPrep,
    JumpAir,
    Land,
    Sit,
    LieDown,
    Sleep,
    Wake,
    GetUp,
    WorkApproach,
    WorkSettle,
    WorkTyping,
    WorkTired,
    WorkAnnoyed,
    Yawn,
    Recover,
    UserReaction,
}

/// <summary>把高层动作请求路由为合法的连续过渡，禁止危险 Pose 瞬切。</summary>
internal sealed class MaotaiAnimationGraph
{
    private MaotaiMotionState _requestedState;
    private double _transitionElapsedSeconds;
    private double _transitionDurationSeconds;

    public MaotaiAnimationGraph(MaotaiMotionState initialState)
    {
        ActiveState            = initialState;
        PreviousState          = initialState;
        TargetState            = initialState;
        _requestedState        = initialState;
        TransitionProgress     = 1.0;
    }

    public MaotaiMotionState ActiveState { get; private set; }

    public MaotaiMotionState PreviousState { get; private set; }

    public MaotaiMotionState TargetState { get; private set; }

    public double TransitionProgress { get; private set; }

    public bool IsTransitioning => TransitionProgress < 1.0;

    /// <summary>请求最终动作；图只进入当前合法的下一跳，不允许跨越必要过渡。</summary>
    public void Request(MaotaiMotionState target)
    {
        _requestedState = target;
        if (target == ActiveState && !IsTransitioning)
        {
            TargetState = target;
            return;
        }

        var next = ResolveNextHop(ActiveState, target);
        BeginHop(next);
    }

    /// <summary>按连续时间推进过渡；完成一跳后自动进入通往最终请求的下一跳。</summary>
    public void Update(double deltaTime)
    {
        if (!double.IsFinite(deltaTime))
        {
            return;
        }

        var dt = Math.Clamp(deltaTime, 0.0, 0.05);
        if (dt <= 0)
        {
            return;
        }

        if (IsTransitioning)
        {
            _transitionElapsedSeconds += dt;
            TransitionProgress = Math.Clamp(
                _transitionElapsedSeconds / Math.Max(_transitionDurationSeconds, 0.000001),
                0.0,
                1.0);
            if (TransitionProgress < 1.0)
            {
                return;
            }
        }

        if (ActiveState == _requestedState)
        {
            TargetState = ActiveState;
            return;
        }

        var next = ResolveNextHop(ActiveState, _requestedState);
        BeginHop(next);
    }

    /// <summary>用户交互结束后改写最终请求，不回放过时的历史业务状态。</summary>
    public void ResumeWith(MaotaiMotionState latestBaseState) => Request(latestBaseState);

    private void BeginHop(MaotaiMotionState next)
    {
        if (next == ActiveState)
        {
            TargetState        = ActiveState;
            TransitionProgress = 1.0;
            return;
        }

        PreviousState               = ActiveState;
        ActiveState                 = next;
        TargetState                 = next;
        _transitionElapsedSeconds   = 0.0;
        _transitionDurationSeconds  = GetTransitionDurationSeconds(PreviousState, next);
        TransitionProgress          = 0.0;
    }

    private static MaotaiMotionState ResolveNextHop(
        MaotaiMotionState current,
        MaotaiMotionState requested)
    {
        if (current == requested)
        {
            return current;
        }

        if (requested == MaotaiMotionState.JumpAir)
        {
            return current switch
            {
                MaotaiMotionState.Run      => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk     => MaotaiMotionState.JumpPrep,
                MaotaiMotionState.Idle     => MaotaiMotionState.JumpPrep,
                MaotaiMotionState.JumpPrep => MaotaiMotionState.JumpAir,
                MaotaiMotionState.JumpAir  => MaotaiMotionState.JumpAir,
                MaotaiMotionState.Land     => MaotaiMotionState.Idle,
                _                          => ReturnTowardIdle(current),
            };
        }

        if (requested == MaotaiMotionState.Sleep)
        {
            return current switch
            {
                MaotaiMotionState.Run      => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk     => MaotaiMotionState.Idle,
                MaotaiMotionState.Idle     => MaotaiMotionState.Sit,
                MaotaiMotionState.Sit      => MaotaiMotionState.LieDown,
                MaotaiMotionState.LieDown  => MaotaiMotionState.Sleep,
                MaotaiMotionState.Sleep    => MaotaiMotionState.Sleep,
                _                          => ReturnTowardIdle(current),
            };
        }

        if (requested == MaotaiMotionState.Run)
        {
            return current switch
            {
                MaotaiMotionState.Idle    => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk    => MaotaiMotionState.Run,
                MaotaiMotionState.Run     => MaotaiMotionState.Run,
                MaotaiMotionState.Sleep   => MaotaiMotionState.Wake,
                MaotaiMotionState.Wake    => MaotaiMotionState.GetUp,
                MaotaiMotionState.LieDown => MaotaiMotionState.GetUp,
                MaotaiMotionState.GetUp   => MaotaiMotionState.Idle,
                MaotaiMotionState.Sit     => MaotaiMotionState.Idle,
                _                         => ReturnTowardIdle(current),
            };
        }

        if (requested == MaotaiMotionState.WorkTyping)
        {
            return current switch
            {
                MaotaiMotionState.Run          => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk         => MaotaiMotionState.WorkApproach,
                MaotaiMotionState.Idle         => MaotaiMotionState.WorkApproach,
                MaotaiMotionState.WorkApproach => MaotaiMotionState.WorkSettle,
                MaotaiMotionState.WorkSettle   => MaotaiMotionState.WorkTyping,
                MaotaiMotionState.WorkTired    => MaotaiMotionState.Recover,
                MaotaiMotionState.WorkAnnoyed  => MaotaiMotionState.Recover,
                MaotaiMotionState.Yawn         => MaotaiMotionState.WorkTyping,
                MaotaiMotionState.Recover      => MaotaiMotionState.WorkTyping,
                MaotaiMotionState.Sleep        => MaotaiMotionState.Wake,
                MaotaiMotionState.Wake         => MaotaiMotionState.GetUp,
                MaotaiMotionState.LieDown      => MaotaiMotionState.GetUp,
                MaotaiMotionState.GetUp        => MaotaiMotionState.Idle,
                _                              => ReturnTowardIdle(current),
            };
        }

        if (requested == MaotaiMotionState.Idle)
        {
            return ReturnTowardIdle(current);
        }

        if (requested is MaotaiMotionState.WorkTired or MaotaiMotionState.WorkAnnoyed)
        {
            return current == MaotaiMotionState.WorkTyping
                ? requested
                : ResolveNextHop(current, MaotaiMotionState.WorkTyping);
        }

        if (requested == MaotaiMotionState.UserReaction)
        {
            return MaotaiMotionState.UserReaction;
        }

        return requested;
    }

    private static MaotaiMotionState ReturnTowardIdle(MaotaiMotionState current) =>
        current switch
        {
            MaotaiMotionState.Run          => MaotaiMotionState.Walk,
            MaotaiMotionState.Walk         => MaotaiMotionState.Idle,
            MaotaiMotionState.JumpPrep     => MaotaiMotionState.Land,
            MaotaiMotionState.JumpAir      => MaotaiMotionState.Land,
            MaotaiMotionState.Land         => MaotaiMotionState.Idle,
            MaotaiMotionState.Sleep        => MaotaiMotionState.Wake,
            MaotaiMotionState.Wake         => MaotaiMotionState.GetUp,
            MaotaiMotionState.LieDown      => MaotaiMotionState.GetUp,
            MaotaiMotionState.Sit          => MaotaiMotionState.Idle,
            MaotaiMotionState.GetUp        => MaotaiMotionState.Idle,
            MaotaiMotionState.WorkApproach => MaotaiMotionState.Idle,
            MaotaiMotionState.WorkSettle   => MaotaiMotionState.Idle,
            MaotaiMotionState.WorkTyping   => MaotaiMotionState.Idle,
            MaotaiMotionState.WorkTired    => MaotaiMotionState.Recover,
            MaotaiMotionState.WorkAnnoyed  => MaotaiMotionState.Recover,
            MaotaiMotionState.Yawn         => MaotaiMotionState.Recover,
            MaotaiMotionState.Recover      => MaotaiMotionState.Idle,
            MaotaiMotionState.UserReaction => MaotaiMotionState.Idle,
            _                              => MaotaiMotionState.Idle,
        };

    private static double GetTransitionDurationSeconds(
        MaotaiMotionState from,
        MaotaiMotionState to)
    {
        _ = from;
        return to switch
        {
            MaotaiMotionState.JumpPrep     => 0.18,
            MaotaiMotionState.JumpAir      => 0.08,
            MaotaiMotionState.Land         => 0.20,
            MaotaiMotionState.Sit          => 0.28,
            MaotaiMotionState.LieDown      => 0.34,
            MaotaiMotionState.Sleep        => 0.40,
            MaotaiMotionState.Wake         => 0.28,
            MaotaiMotionState.GetUp        => 0.32,
            MaotaiMotionState.WorkApproach => 0.18,
            MaotaiMotionState.WorkSettle   => 0.28,
            MaotaiMotionState.WorkTyping   => 0.20,
            MaotaiMotionState.UserReaction => 0.12,
            _                              => 0.16,
        };
    }
}
