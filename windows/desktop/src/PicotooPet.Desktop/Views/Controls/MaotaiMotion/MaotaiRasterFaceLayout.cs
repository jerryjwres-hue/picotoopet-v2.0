using System.Windows;
using System.Windows.Controls;

namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 把动态面部 PNG 校准到当前 head shell；只在 Renderer 初始化时写一次 Canvas/ZIndex。
/// Motion Engine 仍只负责表情状态与自主视线，不感知具体光栅素材的像素偏移。
/// </summary>
internal static class MaotaiRasterFaceLayout
{
    private const double EarTop = -20.5;
    private const double EyeTop = -16.0;
    private const double MuzzleTop = -13.0;
    private const double MouthTop = -2.0;
    private const double PupilHorizontalCorrection = 5.0;
    private const double PupilVerticalCorrection = -5.0;

    public static void Configure(Panel headPanel)
    {
        ArgumentNullException.ThrowIfNull(headPanel);

        foreach (var child in headPanel.Children)
        {
            if (child is not FrameworkElement element)
            {
                continue;
            }

            switch (element.Name)
            {
                case "MaotaiV2EarLeft":
                case "MaotaiV2EarRight":
                    Canvas.SetTop(element, EarTop);
                    Panel.SetZIndex(element, 2);
                    break;

                case "MaotaiV2HeadphoneBand":
                    Panel.SetZIndex(element, 4);
                    break;

                case "MaotaiV2Head":
                    Panel.SetZIndex(element, 8);
                    break;

                case "MaotaiV2Muzzle":
                    Canvas.SetTop(element, MuzzleTop);
                    Panel.SetZIndex(element, 10);
                    break;

                case "MaotaiV2EyeLeftOpen":
                case "MaotaiV2EyeRightOpen":
                case "MaotaiV2EyeLeftHalf":
                case "MaotaiV2EyeRightHalf":
                case "MaotaiV2EyeLeftClosed":
                case "MaotaiV2EyeRightClosed":
                    Canvas.SetTop(element, EyeTop);
                    Panel.SetZIndex(element, 20);
                    break;

                case "MaotaiV2PupilLeft":
                case "MaotaiV2PupilRight":
                    Panel.SetZIndex(element, 22);
                    break;

                case "MaotaiV2BrowLeft":
                case "MaotaiV2BrowRight":
                    Panel.SetZIndex(element, 24);
                    break;

                case "MaotaiV2MouthSmile":
                case "MaotaiV2MouthTired":
                case "MaotaiV2MouthAnnoyed":
                case "MaotaiV2MouthYawn":
                case "MaotaiV2MouthTongue":
                    Canvas.SetTop(element, MouthTop);
                    Panel.SetZIndex(element, 30);
                    break;

                case "MaotaiV2HeadphoneLeft":
                case "MaotaiV2HeadphoneRight":
                    Panel.SetZIndex(element, 40);
                    break;
            }
        }
    }

    public static double CalibratePupilX(double rawX, bool isLeft) =>
        rawX + (isLeft ? -PupilHorizontalCorrection : PupilHorizontalCorrection);

    public static double CalibratePupilY(double rawY) =>
        rawY + PupilVerticalCorrection;
}
