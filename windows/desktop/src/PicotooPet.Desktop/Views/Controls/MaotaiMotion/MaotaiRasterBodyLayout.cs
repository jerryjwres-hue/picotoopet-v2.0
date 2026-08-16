using System.Windows;
using System.Windows.Controls;

namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 最终 V2 光栅素材的身体比例与遮挡校准；只在 Renderer 初始化时执行一次。
/// 运动数学仍由 Motion Engine 负责，这里只处理素材自身的显示框与 Z-order。
/// </summary>
internal static class MaotaiRasterBodyLayout
{
    public static void Configure(Panel bodyPanel)
    {
        ArgumentNullException.ThrowIfNull(bodyPanel);

        foreach (var child in bodyPanel.Children)
        {
            if (child is not FrameworkElement element)
            {
                continue;
            }

            switch (element.Name)
            {
                case "MaotaiV2Shadow":
                    Panel.SetZIndex(element, 0);
                    break;

                case "MaotaiV2TailBase":
                case "MaotaiV2TailMid":
                case "MaotaiV2TailTip":
                    Panel.SetZIndex(element, 6);
                    break;

                case "MaotaiV2HindLeftUpper":
                case "MaotaiV2HindLeftLower":
                case "MaotaiV2HindRightUpper":
                case "MaotaiV2HindRightLower":
                    Panel.SetZIndex(element, 10);
                    break;

                case "MaotaiV2HindLeftPaw":
                case "MaotaiV2HindRightPaw":
                    Panel.SetZIndex(element, 12);
                    break;

                case "MaotaiV2FrontLeftUpper":
                case "MaotaiV2FrontLeftLower":
                case "MaotaiV2FrontRightUpper":
                case "MaotaiV2FrontRightLower":
                    Panel.SetZIndex(element, 16);
                    break;

                case "MaotaiV2TorsoNeutral":
                    ConfigureImage(element, 104.0, 82.0, -52.0, -41.0, 20);
                    break;

                case "MaotaiV2TorsoCrouch":
                    ConfigureImage(element, 108.0, 76.0, -54.0, -38.0, 20);
                    break;

                case "MaotaiV2TorsoStretch":
                    ConfigureImage(element, 100.0, 88.0, -50.0, -44.0, 20);
                    break;

                case "MaotaiV2ChestFur":
                    ConfigureImage(element, 52.0, 42.0, -26.0, -27.0, 24);
                    break;

                case "MaotaiV2FrontLeftPaw":
                case "MaotaiV2FrontRightPaw":
                    Panel.SetZIndex(element, 30);
                    break;

                case "MaotaiV2HeadBone":
                    Panel.SetZIndex(element, 40);
                    break;
            }
        }
    }

    private static void ConfigureImage(
        FrameworkElement element,
        double width,
        double height,
        double left,
        double top,
        int zIndex)
    {
        element.Width  = width;
        element.Height = height;
        Canvas.SetLeft(element, left);
        Canvas.SetTop(element, top);
        Panel.SetZIndex(element, zIndex);
    }
}
