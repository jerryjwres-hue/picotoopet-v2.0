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
    private const double HeadVisualScaleX = 0.80;
    private const double HeadVisualScaleY = 0.86;
    private const double EarTop = -28.0;
    private const double EyeTop = -14.0;
    private const double MuzzleTop = -8.0;
    private const double MouthTop = 2.0;
    private const double PupilHorizontalCorrection = 3.0;
    private const double PupilVerticalCorrection = -3.0;

    public static void Configure(System.Windows.Controls.Panel headPanel)
    {
        ArgumentNullException.ThrowIfNull(headPanel);

        // Canine profile       : keep the real raster head slightly taller/narrower so it never reads as a circular mascot ball.
        // Motion ownership     : dynamic HeadScale remains Motion Engine-owned; this only calibrates raster proportions once.
        headPanel.LayoutTransform = new ScaleTransform(HeadVisualScaleX, HeadVisualScaleY);

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
                    ConfigureFaceBox(element, 66.0, 42.0, -33.0, -38.0);
                    System.Windows.Controls.Panel.SetZIndex(element, 4);
                    break;

                case "MaotaiV2Head":
                    System.Windows.Controls.Panel.SetZIndex(element, 8);
                    break;

                case "MaotaiV2Muzzle":
                    ConfigureCentered(element, 32.0, 22.0, MuzzleTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 10);
                    break;

                case "MaotaiV2EyeLeftOpen":
                case "MaotaiV2EyeLeftHalf":
                case "MaotaiV2EyeLeftClosed":
                    ConfigureFaceBox(element, 16.0, 14.0, -16.0, EyeTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 20);
                    break;

                case "MaotaiV2EyeRightOpen":
                case "MaotaiV2EyeRightHalf":
                case "MaotaiV2EyeRightClosed":
                    ConfigureFaceBox(element, 16.0, 14.0, 0.0, EyeTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 20);
                    break;

                case "MaotaiV2PupilLeft":
                case "MaotaiV2PupilRight":
                    element.Width  = 7.0;
                    element.Height = 7.0;
                    Canvas.SetLeft(element, -3.5);
                    Canvas.SetTop(element, -3.5);
                    System.Windows.Controls.Panel.SetZIndex(element, 22);
                    break;

                case "MaotaiV2BrowLeft":
                    ConfigureFaceBox(element, 18.0, 9.0, -18.0, -16.0);
                    System.Windows.Controls.Panel.SetZIndex(element, 24);
                    break;

                case "MaotaiV2BrowRight":
                    ConfigureFaceBox(element, 18.0, 9.0, 0.0, -16.0);
                    System.Windows.Controls.Panel.SetZIndex(element, 24);
                    break;

                case "MaotaiV2MouthSmile":
                case "MaotaiV2MouthTired":
                case "MaotaiV2MouthAnnoyed":
                case "MaotaiV2MouthYawn":
                case "MaotaiV2MouthTongue":
                    ConfigureCentered(element, 22.0, 15.0, MouthTop);
                    System.Windows.Controls.Panel.SetZIndex(element, 30);
                    break;

                case "MaotaiV2HeadphoneLeft":
                    ConfigureFaceBox(element, 20.0, 28.0, -35.0, -10.0);
                    System.Windows.Controls.Panel.SetZIndex(element, 40);
                    break;

                case "MaotaiV2HeadphoneRight":
                    ConfigureFaceBox(element, 20.0, 28.0, 15.0, -10.0);
                    System.Windows.Controls.Panel.SetZIndex(element, 40);
                    break;
            }
        }
    }

    private static void ConfigureCentered(
        FrameworkElement element,
        double width,
        double height,
        double top)
    {
        ConfigureFaceBox(element, width, height, -(width / 2.0), top);
    }

    private static void ConfigureFaceBox(
        FrameworkElement element,
        double width,
        double height,
        double left,
        double top)
    {
        element.Width  = width;
        element.Height = height;
        Canvas.SetLeft(element, left);
        Canvas.SetTop(element, top);
    }

    public static double CalibratePupilX(double rawX, bool isLeft) =>
        rawX + (isLeft ? -PupilHorizontalCorrection : PupilHorizontalCorrection);

    public static double CalibratePupilY(double rawY) =>
        rawY + PupilVerticalCorrection;
}
