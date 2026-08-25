namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>一帧实际可见的脸部图层权重；纯值类型，不持有 WPF 图层或动画对象。</summary>
internal readonly record struct MaotaiFaceLayerWeights(
    double EyeOpen,
    double EyeHalf,
    double EyeClosed,
    double MouthSmile,
    double MouthTired,
    double MouthAnnoyed,
    double MouthYawn,
    double MouthTongue)
{
    public static MaotaiFaceLayerWeights OpenSmile => new(
        EyeOpen: 1.0,
        EyeHalf: 0.0,
        EyeClosed: 0.0,
        MouthSmile: 1.0,
        MouthTired: 0.0,
        MouthAnnoyed: 0.0,
        MouthYawn: 0.0,
        MouthTongue: 0.0);

    public static MaotaiFaceLayerWeights FromStates(
        MaotaiEyeState eyeState,
        MaotaiMouthState mouthState) =>
        new(
            EyeOpen: eyeState == MaotaiEyeState.Open ? 1.0 : 0.0,
            EyeHalf: eyeState == MaotaiEyeState.Half ? 1.0 : 0.0,
            EyeClosed: eyeState == MaotaiEyeState.Closed ? 1.0 : 0.0,
            MouthSmile: mouthState == MaotaiMouthState.Smile ? 1.0 : 0.0,
            MouthTired: mouthState == MaotaiMouthState.Tired ? 1.0 : 0.0,
            MouthAnnoyed: mouthState == MaotaiMouthState.Annoyed ? 1.0 : 0.0,
            MouthYawn: mouthState == MaotaiMouthState.Yawn ? 1.0 : 0.0,
            MouthTongue: mouthState == MaotaiMouthState.Tongue ? 1.0 : 0.0);

    /// <summary>
    /// 把离散表情状态映射到连续 PNG 权重。普通 graph 边界使用 PreviousMotionState -> MotionState 的同一 transition envelope；
    /// Yawn 保留原有独立开口曲线；自然眨眼和 Offline/Error 等强覆盖不延迟。
    /// </summary>
    public static MaotaiFaceLayerWeights Resolve(
        MaotaiMotionState motionState,
        MaotaiMotionState previousMotionState,
        double motionTransitionBlend,
        MaotaiEyeState eyeState,
        MaotaiMouthState mouthState,
        double yawnProgress,
        double mouthOpenAmount)
    {
        if (motionState == MaotaiMotionState.Yawn)
        {
            return ForYawn(yawnProgress, mouthOpenAmount);
        }

        var current = FromStates(eyeState, mouthState);

        // Strong/cosmetic override: if the resolved expression differs from the ordinary face for this motion node,
        // it came from Offline/Error, pointer interaction, or the deterministic blink scheduler and must remain immediate.
        if (eyeState != ExpectedEyeState(motionState) ||
            mouthState != ExpectedMouthState(motionState))
        {
            return current;
        }

        var transition = Clamp01(motionTransitionBlend);
        if (previousMotionState == motionState || transition >= 1.0)
        {
            return current;
        }

        var previous = ForMotionStateEndpoint(previousMotionState);
        return Lerp(previous, current, transition);
    }

    /// <summary>保持现有 Yawn Renderer 的开口/收口曲线，只把所有权收敛到纯值策略。</summary>
    public static MaotaiFaceLayerWeights ForYawn(
        double yawnProgress,
        double mouthOpenAmount)
    {
        var progress = Clamp01(yawnProgress);
        var opening  = Clamp01(mouthOpenAmount);
        var baseFace = 1.0 - opening;
        var tired    = baseFace * (1.0 - progress);
        var smile    = baseFace * progress;

        return new MaotaiFaceLayerWeights(
            EyeOpen: smile,
            EyeHalf: tired,
            EyeClosed: opening,
            MouthSmile: smile,
            MouthTired: tired,
            MouthAnnoyed: 0.0,
            MouthYawn: opening,
            MouthTongue: 0.0);
    }

    public static MaotaiFaceLayerWeights Lerp(
        in MaotaiFaceLayerWeights from,
        in MaotaiFaceLayerWeights to,
        double amount)
    {
        var t = Clamp01(amount);
        return new MaotaiFaceLayerWeights(
            EyeOpen: Mix(from.EyeOpen, to.EyeOpen, t),
            EyeHalf: Mix(from.EyeHalf, to.EyeHalf, t),
            EyeClosed: Mix(from.EyeClosed, to.EyeClosed, t),
            MouthSmile: Mix(from.MouthSmile, to.MouthSmile, t),
            MouthTired: Mix(from.MouthTired, to.MouthTired, t),
            MouthAnnoyed: Mix(from.MouthAnnoyed, to.MouthAnnoyed, t),
            MouthYawn: Mix(from.MouthYawn, to.MouthYawn, t),
            MouthTongue: Mix(from.MouthTongue, to.MouthTongue, t));
    }

    private static MaotaiFaceLayerWeights ForMotionStateEndpoint(MaotaiMotionState state) =>
        state == MaotaiMotionState.Yawn
            ? ForYawn(1.0, 0.0)
            : FromStates(ExpectedEyeState(state), ExpectedMouthState(state));

    private static MaotaiEyeState ExpectedEyeState(MaotaiMotionState state) =>
        state switch
        {
            MaotaiMotionState.Sleep       => MaotaiEyeState.Closed,
            MaotaiMotionState.Wake        => MaotaiEyeState.Half,
            MaotaiMotionState.WorkTired   => MaotaiEyeState.Half,
            MaotaiMotionState.WorkAnnoyed => MaotaiEyeState.Half,
            MaotaiMotionState.Yawn        => MaotaiEyeState.Closed,
            _                             => MaotaiEyeState.Open,
        };

    private static MaotaiMouthState ExpectedMouthState(MaotaiMotionState state) =>
        state switch
        {
            MaotaiMotionState.Sleep        => MaotaiMouthState.Tired,
            MaotaiMotionState.WorkTired    => MaotaiMouthState.Tired,
            MaotaiMotionState.WorkAnnoyed  => MaotaiMouthState.Annoyed,
            MaotaiMotionState.Yawn         => MaotaiMouthState.Yawn,
            MaotaiMotionState.UserReaction => MaotaiMouthState.Tongue,
            _                              => MaotaiMouthState.Smile,
        };

    private static double Clamp01(double value) =>
        Math.Clamp(double.IsFinite(value) ? value : 0.0, 0.0, 1.0);

    private static double Mix(double from, double to, double amount) =>
        from + ((to - from) * amount);
}
