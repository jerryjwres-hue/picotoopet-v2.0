using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 把动态面部 PNG 校准到当前 head shell；只在 Renderer 初始化时写一次 Canvas/ZIndex。
/// Motion Engine 仍只负责表情状态与自主视线，不感知具体光栅素材的像素偏移。
/// </summary>
internal static class MaotaiRasterFaceLayout
{
    private const double HeadVisualScale = 0.96;
    private const double EarTop = -20.5;
    private const double EyeTop = -16.0;
    private const double MuzzleTop = -13.0;
    private const double MouthTop = -2.0;
    private const double PupilHorizontalCorrection = 5.0;
    private const double PupilVerticalCorrection = -5.0;

    public static void Configure(System.Windows.Controls.Panel headPanel)
    {
        ArgumentNullException.ThrowIfNull(headPanel);

        // Static art-fit scale : new neutral fur shell is intentionally fuller; dynamic HeadScale remains Motion Engine-owned.
        headPanel.LayoutTransform = new ScaleTransform(HeadVisualScale, HeadVisualScale);

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
                    System.Windows.Controls.Panel.SetZIndex(element, 2);
                    break;

                case "MaotaiV2HeadphoneBand":
                    System.Windows.Controls.Panel.SetZIndex(element, 4);
                    break;

                case "MaotaiV2Head":
                    System.Windows.Controls.Panel.SetZIndex(element, 8);
                    break;

                case "MaotaiV2Muzzle":
                    Canvas.SetTop(element, MuzzleTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 10);
                    break;

                case "MaotaiV2EyeLeftOpen":
                case "MaotaiV2EyeRightOpen":
                case "MaotaiV2EyeLeftHalf":
                case "MaotaiV2EyeRightHalf":
                case "MaotaiV2EyeLeftClosed":
                case "MaotaiV2EyeRightClosed":
                    Canvas.SetTop(element, EyeTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 20);
                    break;

                case "MaotaiV2PupilLeft":
                case "MaotaiV2PupilRight":
                    System.Windows.Controls.Panel.SetZIndex(element, 22);
                    break;

                case "MaotaiV2BrowLeft":
                case "MaotaiV2BrowRight":
                    System.Windows.Controls.Panel.SetZIndex(element, 24);
                    break;

                case "MaotaiV2MouthSmile":
                case "MaotaiV2MouthTired":
                case "MaotaiV2MouthAnnoyed":
                case "MaotaiV2MouthYawn":
                case "MaotaiV2MouthTongue":
                    Canvas.SetTop(element, MouthTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 30);
                    break;

                case "MaotaiV2HeadphoneLeft":
                case "MaotaiV2HeadphoneRight":
                    System.Windows.Controls.Panel.SetZIndex(element, 40);
                    break;
            }
        }
    }

    public static double CalibratePupilX(double rawX, bool isLeft) =>
        rawX + (isLeft ? -PupilHorizontalCorrection : PupilHorizontalCorrection);

    public static double CalibratePupilY(double rawY) =>
        rawY + PupilVerticalCorrection;
}
