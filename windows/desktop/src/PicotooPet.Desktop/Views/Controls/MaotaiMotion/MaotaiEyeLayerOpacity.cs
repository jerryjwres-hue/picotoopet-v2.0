namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 独立眼部光栅的可见性权重。瞳孔只属于睁眼图层；眨眼交叉淡化时
/// 必须跟随 open-eye 权重，避免半闭或闭眼阶段出现悬浮瞳孔。
/// </summary>
internal static class MaotaiEyeLayerOpacity
{
    public static double PupilFromOpenWeight(double openWeight)
    {
        if (!double.IsFinite(openWeight))
        {
            return 0.0;
        }

        return Math.Clamp(openWeight, 0.0, 1.0);
    }
}
