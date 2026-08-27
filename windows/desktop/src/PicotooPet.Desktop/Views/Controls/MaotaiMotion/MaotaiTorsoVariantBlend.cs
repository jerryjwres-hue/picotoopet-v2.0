namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>把连续 bodyScaleY 映射到三张独立 torso surface；只产出归一化权重，不持有 UI 状态。</summary>
internal readonly record struct MaotaiTorsoVariantBlend(
    double Neutral,
    double Crouch,
    double Stretch)
{
    private const double CrouchRange  = 0.085;
    private const double StretchRange = 0.070;

    /// <summary>中性附近平滑渐变；非法输入 fail-safe 回 neutral，禁止状态边界硬切。</summary>
    public static MaotaiTorsoVariantBlend FromScaleY(double scaleY)
    {
        if (!double.IsFinite(scaleY))
        {
            return new MaotaiTorsoVariantBlend(
                Neutral: 1.0,
                Crouch: 0.0,
                Stretch: 0.0);
        }

        var crouch = scaleY < 1.0
            ? SmoothStep(Math.Clamp((1.0 - scaleY) / CrouchRange, 0.0, 1.0))
            : 0.0;
        var stretch = scaleY > 1.0
            ? SmoothStep(Math.Clamp((scaleY - 1.0) / StretchRange, 0.0, 1.0))
            : 0.0;
        var neutral = 1.0 - Math.Max(crouch, stretch);

        return new MaotaiTorsoVariantBlend(
            Neutral: neutral,
            Crouch: crouch,
            Stretch: stretch);
    }

    private static double SmoothStep(double value) =>
        value * value * (3.0 - (2.0 * value));
}
