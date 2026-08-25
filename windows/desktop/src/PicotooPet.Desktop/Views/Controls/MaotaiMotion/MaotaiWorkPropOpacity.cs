namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>把 AnimationGraph 的连续过渡包络映射为工作道具显隐；不持有 WPF 对象或运行时状态。</summary>
internal static class MaotaiWorkPropOpacity
{
    public static double Resolve(
        MaotaiMotionState currentState,
        MaotaiMotionState previousState,
        double transitionBlend)
    {
        var currentVisible  = IsWorkVisualState(currentState);
        var previousVisible = IsWorkVisualState(previousState);
        if (currentVisible == previousVisible)
        {
            return currentVisible ? 1.0 : 0.0;
        }

        var t = Math.Clamp(
            double.IsFinite(transitionBlend) ? transitionBlend : 0.0,
            0.0,
            1.0);
        return currentVisible ? t : 1.0 - t;
    }

    private static bool IsWorkVisualState(MaotaiMotionState state) =>
        state is MaotaiMotionState.WorkApproach or
            MaotaiMotionState.WorkSettle or
            MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover;
}
