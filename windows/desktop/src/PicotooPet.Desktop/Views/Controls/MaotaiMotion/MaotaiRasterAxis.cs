namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 统一 Motion Engine 数学角度与光栅素材自身零轴之间的约定。
/// IK 以 +X 为 0°；腿部 PNG 的自然朝向为向下，因此渲染前固定减去 90°。
/// </summary>
internal static class MaotaiRasterAxis
{
    public static double LegRotationFromIkDegrees(double ikAngleDeg) =>
        ikAngleDeg - 90.0;
}
