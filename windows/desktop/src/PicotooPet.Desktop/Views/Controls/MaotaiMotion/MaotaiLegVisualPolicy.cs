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
        if (IsLocomotionState(state))
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

        return StableStyle();
    }

    /// <summary>
    /// 只对真实位移状态做视觉包络插值。blend=0 与稳定站姿完全一致；blend=1 才到达运动目标样式，
    /// 因此状态机先切到 Walk/Run/WorkApproach 时不会立即闪出 Lower 或把后腿突然压暗。
    /// </summary>
    public static MaotaiLegVisualStyle ResolveForBlend(
        MaotaiMotionState state,
        bool isFront,
        double locomotionBlend)
    {
        var target = Resolve(state, isFront);
        if (!IsLocomotionState(state))
        {
            return target;
        }

        var start = StableStyle();
        var t     = Math.Clamp(
            double.IsFinite(locomotionBlend) ? locomotionBlend : 0.0,
            0.0,
            1.0);

        return target with
        {
            UpperOpacity = Lerp(start.UpperOpacity, target.UpperOpacity, t),
            LowerOpacity = Lerp(start.LowerOpacity, target.LowerOpacity, t),
            PawOpacity   = Lerp(start.PawOpacity, target.PawOpacity, t),
            PawScaleX    = Lerp(start.PawScaleX, target.PawScaleX, t),
            UpperScaleX  = Lerp(start.UpperScaleX, target.UpperScaleX, t),
            LowerScaleX  = Lerp(start.LowerScaleX, target.LowerScaleX, t),
        };
    }

    private static bool IsLocomotionState(MaotaiMotionState state) =>
        state is MaotaiMotionState.Walk or
            MaotaiMotionState.Run or
            MaotaiMotionState.WorkApproach;

    private static MaotaiLegVisualStyle StableStyle() =>
        new(
            UseArticulation: false,
            UpperOpacity: 1.0,
            LowerOpacity: 0.0,
            PawOpacity: 1.0,
            PawScaleX: 1.0,
            UpperScaleX: 0.86,
            LowerScaleX: 0.80);

    private static double Lerp(double from, double to, double t) =>
        from + ((to - from) * Math.Clamp(t, 0.0, 1.0));
}
