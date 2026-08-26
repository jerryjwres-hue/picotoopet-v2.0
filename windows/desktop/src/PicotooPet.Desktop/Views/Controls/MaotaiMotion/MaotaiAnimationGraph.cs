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

/// <summary>工作状态内部的自然循环阶段；只影响表现，不改变真实 Working 状态。</summary>
internal enum MaotaiWorkCyclePhase
{
    AwaitTyping,
    TypingBeforeTired,
    Tired,
    Yawn,
    TypingBeforeAnnoyed,
    Annoyed,
    Recover,
}

/// <summary>把高层动作请求路由为合法的连续过渡，禁止危险 Pose 瞬切。</summary>
internal sealed class MaotaiAnimationGraph
{
    private MaotaiMotionState _requestedState;
    private double _transitionElapsedSeconds;
    private double _transitionDurationSeconds;
    private MaotaiWorkCyclePhase _workCyclePhase = MaotaiWorkCyclePhase.AwaitTyping;
    private double _workPhaseElapsedSeconds;

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
        if (target != MaotaiMotionState.WorkTyping)
        {
            ResetWorkCycle();
        }

        _requestedState = target;
        if (target == MaotaiMotionState.Idle &&
            ActiveState == MaotaiMotionState.Recover &&
            IsTransitioning)
        {
            // Recover already converges to neutral. Keep the latest Idle request latched,
            // but let this neutralizing hop finish instead of restarting from a partial pose.
            return;
        }

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

        // Work cycle          : while the latest real request remains WorkTyping, internal mood nodes
        //                       may advance without replacing the base request or switching whole images.
        if (_requestedState == MaotaiMotionState.WorkTyping &&
            IsWorkFamilyState(ActiveState))
        {
            UpdateWorkCycle(dt);
            return;
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

    private void UpdateWorkCycle(double dt)
    {
        switch (_workCyclePhase)
        {
            case MaotaiWorkCyclePhase.AwaitTyping:
                if (ActiveState == MaotaiMotionState.WorkTyping)
                {
                    _workCyclePhase        = MaotaiWorkCyclePhase.TypingBeforeTired;
                    _workPhaseElapsedSeconds = 0.0;
                }
                else
                {
                    ContinueTowardWorkTyping();
                }
                break;

            case MaotaiWorkCyclePhase.TypingBeforeTired:
                if (ActiveState != MaotaiMotionState.WorkTyping)
                {
                    ContinueTowardWorkTyping();
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 3.0)
                {
                    // Fatigue onset       : slow into tired before opening the mouth for a yawn.
                    _workCyclePhase          = MaotaiWorkCyclePhase.Tired;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.WorkTired);
                }
                break;

            case MaotaiWorkCyclePhase.Tired:
                if (ActiveState != MaotaiMotionState.WorkTired)
                {
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 0.70)
                {
                    // Yawn handoff        : preserve one continuous pose graph instead of swapping artwork.
                    _workCyclePhase          = MaotaiWorkCyclePhase.Yawn;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.Yawn);
                }
                break;

            case MaotaiWorkCyclePhase.Yawn:
                if (ActiveState != MaotaiMotionState.Yawn)
                {
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 0.85)
                {
                    _workCyclePhase          = MaotaiWorkCyclePhase.TypingBeforeAnnoyed;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.WorkTyping);
                }
                break;

            case MaotaiWorkCyclePhase.TypingBeforeAnnoyed:
                if (ActiveState != MaotaiMotionState.WorkTyping)
                {
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 3.5)
                {
                    // Annoyed burst        : brief tension spike, then an explicit recovery transition.
                    _workCyclePhase          = MaotaiWorkCyclePhase.Annoyed;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.WorkAnnoyed);
                }
                break;

            case MaotaiWorkCyclePhase.Annoyed:
                if (ActiveState != MaotaiMotionState.WorkAnnoyed)
                {
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 0.70)
                {
                    _workCyclePhase          = MaotaiWorkCyclePhase.Recover;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.Recover);
                }
                break;

            case MaotaiWorkCyclePhase.Recover:
                if (ActiveState != MaotaiMotionState.Recover)
                {
                    break;
                }

                _workPhaseElapsedSeconds += dt;
                if (_workPhaseElapsedSeconds >= 0.80)
                {
                    _workCyclePhase          = MaotaiWorkCyclePhase.TypingBeforeTired;
                    _workPhaseElapsedSeconds = 0.0;
                    BeginHop(MaotaiMotionState.WorkTyping);
                }
                break;
        }
    }

    private void ContinueTowardWorkTyping()
    {
        if (IsTransitioning || ActiveState == MaotaiMotionState.WorkTyping)
        {
            return;
        }

        BeginHop(ResolveNextHop(ActiveState, MaotaiMotionState.WorkTyping));
    }

    private void ResetWorkCycle()
    {
        _workCyclePhase          = MaotaiWorkCyclePhase.AwaitTyping;
        _workPhaseElapsedSeconds = 0.0;
    }

    private static bool IsWorkFamilyState(MaotaiMotionState state) =>
        state is MaotaiMotionState.WorkApproach or
            MaotaiMotionState.WorkSettle or
            MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover;

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

        if (requested == MaotaiMotionState.Sit)
        {
            return current switch
            {
                MaotaiMotionState.Run      => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk     => MaotaiMotionState.Idle,
                MaotaiMotionState.Idle     => MaotaiMotionState.Sit,
                MaotaiMotionState.Sit      => MaotaiMotionState.Sit,
                MaotaiMotionState.Sleep    => MaotaiMotionState.Wake,
                MaotaiMotionState.Wake     => MaotaiMotionState.GetUp,
                MaotaiMotionState.LieDown  => MaotaiMotionState.GetUp,
                MaotaiMotionState.GetUp    => MaotaiMotionState.Idle,
                _                          => ReturnTowardIdle(current),
            };
        }

        if (requested == MaotaiMotionState.LieDown)
        {
            return current switch
            {
                MaotaiMotionState.Run      => MaotaiMotionState.Walk,
                MaotaiMotionState.Walk     => MaotaiMotionState.Idle,
                MaotaiMotionState.Idle     => MaotaiMotionState.Sit,
                MaotaiMotionState.Sit      => MaotaiMotionState.LieDown,
                MaotaiMotionState.LieDown  => MaotaiMotionState.LieDown,
                MaotaiMotionState.Sleep    => MaotaiMotionState.Wake,
                MaotaiMotionState.Wake     => MaotaiMotionState.GetUp,
                MaotaiMotionState.GetUp    => MaotaiMotionState.Idle,
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
                MaotaiMotionState.WorkTired    => MaotaiMotionState.Yawn,
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

        if (requested == MaotaiMotionState.Look)
        {
            return IsWorkFamilyState(current)
                ? ReturnTowardIdle(current)
                : MaotaiMotionState.Look;
        }

        if (requested is MaotaiMotionState.WorkTired or MaotaiMotionState.WorkAnnoyed)
        {
            return current == MaotaiMotionState.WorkTyping
                ? requested
                : ResolveNextHop(current, MaotaiMotionState.WorkTyping);
        }

        if (requested == MaotaiMotionState.UserReaction)
        {
            return current switch
            {
                MaotaiMotionState.Sleep   => MaotaiMotionState.Wake,
                MaotaiMotionState.Wake    => MaotaiMotionState.GetUp,
                MaotaiMotionState.LieDown => MaotaiMotionState.GetUp,
                MaotaiMotionState.GetUp   => MaotaiMotionState.UserReaction,
                _                         => MaotaiMotionState.UserReaction,
            };
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
            MaotaiMotionState.WorkTired    => 0.28,
            MaotaiMotionState.Yawn         => 0.30,
            MaotaiMotionState.WorkAnnoyed  => 0.22,
            MaotaiMotionState.Recover      => 0.28,
            MaotaiMotionState.UserReaction => 0.12,
            _                              => 0.16,
        };
    }
}
