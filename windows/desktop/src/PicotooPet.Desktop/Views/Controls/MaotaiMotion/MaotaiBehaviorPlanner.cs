namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>来自现有 PetPresentation 的只读基础表现状态。</summary>
internal enum MaotaiBaseState
{
    Resting,
    Working,
    Waiting,
    Offline,
    Error,
}

/// <summary>高于自主行为的直接用户交互类别。</summary>
internal enum MaotaiInteractionKind
{
    None,
    PointerObserve,
    Pat,
    Paw,
    Celebrate,
    Drag,
}

/// <summary>每帧 Motion Engine 唯一输入；不包含 Core/Worker 写接口。</summary>
internal readonly record struct MaotaiMotionInput(
    MaotaiBaseState BaseState,
    double PointerX,
    double PointerY,
    bool PointerInside,
    MaotaiInteractionKind Interaction,
    double StageMinX,
    double StageMaxX,
    double TargetX,
    bool WantsRun,
    bool WantsJump,
    double WorkAnchorX);

/// <summary>只决定高层动作目标，不直接操作 WPF 图层或业务状态。</summary>
internal sealed class MaotaiBehaviorPlanner
{
    public MaotaiMotionState Plan(
        in MaotaiMotionInput input,
        double currentX)
    {
        if (input.Interaction != MaotaiInteractionKind.None)
        {
            return MaotaiMotionState.UserReaction;
        }

        if (input.BaseState == MaotaiBaseState.Offline)
        {
            return MaotaiMotionState.Sleep;
        }

        if (input.BaseState == MaotaiBaseState.Error)
        {
            return MaotaiMotionState.Look;
        }

        if (input.WantsJump)
        {
            return MaotaiMotionState.JumpAir;
        }

        if (input.BaseState == MaotaiBaseState.Working)
        {
            return MaotaiMotionState.WorkTyping;
        }

        if (input.BaseState == MaotaiBaseState.Waiting)
        {
            return MaotaiMotionState.Look;
        }

        var distance = Math.Abs(input.TargetX - currentX);
        if (distance > 2.0)
        {
            return input.WantsRun
                ? MaotaiMotionState.Run
                : MaotaiMotionState.Walk;
        }

        return input.PointerInside
            ? MaotaiMotionState.Look
            : MaotaiMotionState.Idle;
    }
}
