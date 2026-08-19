using System.Windows;
using System.Windows.Controls;

namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>
/// 最终 V2 光栅素材的身体比例与遮挡校准；只在 Renderer 初始化时执行一次。
/// 运动数学仍由 Motion Engine 负责，这里只处理素材自身的显示框与 Z-order。
/// </summary>
internal static class MaotaiRasterBodyLayout
{
    public static void Configure(System.Windows.Controls.Panel bodyPanel)
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
                    System.Windows.Controls.Panel.SetZIndex(element, 0);
                    break;

                case "MaotaiV2TailBase":
                case "MaotaiV2TailMid":
                case "MaotaiV2TailTip":
                    System.Windows.Controls.Panel.SetZIndex(element, 6);
                    break;

                case "MaotaiV2HindLeftUpper":
                case "MaotaiV2HindRightUpper":
                    ConfigurePivotedImage(element, 26.0, 42.0, 0.50, 0.15, 10);
                    break;

                case "MaotaiV2HindLeftLower":
                case "MaotaiV2HindRightLower":
                    ConfigurePivotedImage(element, 25.0, 39.0, 0.50, 0.15, 10);
                    break;

                case "MaotaiV2HindLeftPaw":
                case "MaotaiV2HindRightPaw":
                    ConfigurePivotedImage(element, 26.0, 20.0, 0.50, 0.50, 12);
                    break;

                case "MaotaiV2FrontLeftUpper":
                case "MaotaiV2FrontRightUpper":
                    ConfigurePivotedImage(element, 26.0, 43.0, 0.50, 0.15, 16);
                    break;

                case "MaotaiV2FrontLeftLower":
                case "MaotaiV2FrontRightLower":
                    ConfigurePivotedImage(element, 25.0, 40.0, 0.50, 0.15, 16);
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
                    ConfigurePivotedImage(element, 27.0, 20.0, 0.50, 0.50, 30);
                    break;

                case "MaotaiV2HeadBone":
                    System.Windows.Controls.Panel.SetZIndex(element, 40);
                    break;
            }
        }

        ConfigureWorkProps(bodyPanel);
    }

    /// <summary>
    /// 工作道具与身体共用同一个舞台坐标系；只在初始化时校准一次，避免把视觉偏移写进 Motion Engine。
    /// </summary>
    private static void ConfigureWorkProps(System.Windows.Controls.Panel bodyPanel)
    {
        if (bodyPanel.Parent is not FrameworkElement root ||
            root.Parent is not System.Windows.Controls.Panel motionLayer)
        {
            return;
        }

        foreach (var child in motionLayer.Children)
        {
            if (child is FrameworkElement { Name: "MaotaiV2Laptop" } laptop)
            {
                Canvas.SetLeft(laptop, 68.0);
                return;
            }
        }
    }

    private static void ConfigurePivotedImage(
        FrameworkElement element,
        double width,
        double height,
        double pivotX,
        double pivotY,
        int zIndex)
    {
        element.Width = width;
        element.Height = height;
        element.RenderTransformOrigin = new System.Windows.Point(pivotX, pivotY);
        Canvas.SetLeft(element, -(width * pivotX));
        Canvas.SetTop(element, -(height * pivotY));
        System.Windows.Controls.Panel.SetZIndex(element, zIndex);
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
        System.Windows.Controls.Panel.SetZIndex(element, zIndex);
    }
}
