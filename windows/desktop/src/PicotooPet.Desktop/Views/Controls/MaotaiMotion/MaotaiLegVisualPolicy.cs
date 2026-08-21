namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>单条腿在当前状态下的纯视觉显示策略；不修改 Motion Engine 的 IK、锁脚或状态机。</summary>
internal readonly record struct MaotaiLegVisualStyle(
    bool UseArticulation,
    double UpperOpacity,
    double LowerOpacity,
    double PawOpacity,
    double PawScaleX,
    double UpperScaleX,
    double LowerScaleX);

/// <summary>把状态语义映射为腿部显示策略，集中替代 Renderer 内分散的隐藏/压窄 workaround。</summary>
internal static class MaotaiLegVisualPolicy
{
    public static MaotaiLegVisualStyle Resolve(
        MaotaiMotionState state,
        bool isFront)
    {
        var moving = state is MaotaiMotionState.Walk or MaotaiMotionState.Run;
        if (moving)
        {
            // Front locomotion : keep the real IK knee, but render Lower as a narrow fur bridge instead of a second full limb block.
            // Rear depth       : preserve a subordinate rear silhouette and paw contact without exposing another complete articulated stack.
            return isFront
                ? new MaotaiLegVisualStyle(
                    UseArticulation: true,
                    UpperOpacity: 1.0,
                    LowerOpacity: 0.24,
                    PawOpacity: 1.0,
                    PawScaleX: 0.92,
                    UpperScaleX: 0.84,
                    LowerScaleX: 0.58)
                : new MaotaiLegVisualStyle(
                    UseArticulation: false,
                    UpperOpacity: 0.28,
                    LowerOpacity: 0.0,
                    PawOpacity: 0.18,
                    PawScaleX: 0.92,
                    UpperScaleX: 0.80,
                    LowerScaleX: 0.58);
        }

        var folded = state is
            MaotaiMotionState.WorkSettle or
            MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover or
            MaotaiMotionState.LieDown or
            MaotaiMotionState.Sleep or
            MaotaiMotionState.Wake or
            MaotaiMotionState.GetUp;
        if (folded)
        {
            // Folded posture   : long limb silhouettes stay behind torso fur; paws remain for typing/contact semantics.
            return new MaotaiLegVisualStyle(
                UseArticulation: false,
                UpperOpacity: 0.0,
                LowerOpacity: 0.0,
                PawOpacity: 1.0,
                PawScaleX: 1.0,
                UpperScaleX: 0.86,
                LowerScaleX: 0.80);
        }

        // Stable posture      : preserve the cleaner continuous silhouette outside locomotion.
        return new MaotaiLegVisualStyle(
            UseArticulation: false,
            UpperOpacity: 1.0,
            LowerOpacity: 0.0,
            PawOpacity: 1.0,
            PawScaleX: 1.0,
            UpperScaleX: 0.86,
            LowerScaleX: 0.80);
    }
}
