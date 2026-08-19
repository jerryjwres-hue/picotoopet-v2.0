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
                    ConfigureManifestPivotedImage(
                        element,
                        33.0,
                        43.0,
                        MaotaiAssetManifest.HindLeftUpper,
                        10);
                    break;

                case "MaotaiV2HindRightUpper":
                    ConfigureManifestPivotedImage(
                        element,
                        33.0,
                        43.0,
                        MaotaiAssetManifest.HindRightUpper,
                        10);
                    break;

                case "MaotaiV2HindLeftLower":
                    ConfigureManifestPivotedImage(
                        element,
                        32.0,
                        41.0,
                        MaotaiAssetManifest.HindLeftLower,
                        11);
                    break;

                case "MaotaiV2HindRightLower":
                    ConfigureManifestPivotedImage(
                        element,
                        32.0,
                        41.0,
                        MaotaiAssetManifest.HindRightLower,
                        11);
                    break;

                case "MaotaiV2HindLeftPaw":
                    ConfigureManifestPivotedImage(
                        element,
                        36.0,
                        26.0,
                        MaotaiAssetManifest.HindLeftPaw,
                        12);
                    break;

                case "MaotaiV2HindRightPaw":
                    ConfigureManifestPivotedImage(
                        element,
                        36.0,
                        26.0,
                        MaotaiAssetManifest.HindRightPaw,
                        12);
                    break;

                case "MaotaiV2FrontLeftUpper":
                    ConfigureManifestPivotedImage(
                        element,
                        31.0,
                        45.0,
                        MaotaiAssetManifest.FrontLeftUpper,
                        16);
                    break;

                case "MaotaiV2FrontRightUpper":
                    ConfigureManifestPivotedImage(
                        element,
                        31.0,
                        45.0,
                        MaotaiAssetManifest.FrontRightUpper,
                        16);
                    break;

                case "MaotaiV2FrontLeftLower":
                    ConfigureManifestPivotedImage(
                        element,
                        30.0,
                        42.0,
                        MaotaiAssetManifest.FrontLeftLower,
                        17);
                    break;

                case "MaotaiV2FrontRightLower":
                    ConfigureManifestPivotedImage(
                        element,
                        30.0,
                        42.0,
                        MaotaiAssetManifest.FrontRightLower,
                        17);
                    break;

                // Plush torso      : slightly larger body coverage hides shoulder/hip seams while preserving the same body pivot.
                case "MaotaiV2TorsoNeutral":
                    ConfigureImage(element, 112.0, 90.0, -56.0, -45.0, 20);
                    break;

                case "MaotaiV2TorsoCrouch":
                    ConfigureImage(element, 116.0, 84.0, -58.0, -42.0, 20);
                    break;

                case "MaotaiV2TorsoStretch":
                    ConfigureImage(element, 108.0, 96.0, -54.0, -48.0, 20);
                    break;

                case "MaotaiV2ChestFur":
                    ConfigureImage(element, 52.0, 42.0, -26.0, -27.0, 24);
                    break;

                case "MaotaiV2FrontLeftPaw":
                    ConfigureManifestPivotedImage(
                        element,
                        34.0,
                        24.0,
                        MaotaiAssetManifest.FrontLeftPaw,
                        30);
                    break;

                case "MaotaiV2FrontRightPaw":
                    ConfigureManifestPivotedImage(
                        element,
                        34.0,
                        24.0,
                        MaotaiAssetManifest.FrontRightPaw,
                        30);
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
                // Work prop footprint : show the complete laptop as one readable foreground object under both typing paws.
                laptop.Width  = 82.0;
                laptop.Height = 52.0;
                Canvas.SetLeft(laptop, 44.0);
                Canvas.SetTop(laptop, 98.0);
                System.Windows.Controls.Panel.SetZIndex(laptop, 60);
                return;
            }
        }
    }

    /// <summary>
    /// 显示框允许按组合效果缩放，但旋转中心必须来自 Manifest 的原始透明素材 Pivot。
    /// 这样调整肢体 footprint 时仍围绕真正的关节毛发重叠区旋转，不会再次出现“纸片被撕开”的接缝。
    /// </summary>
    private static void ConfigureManifestPivotedImage(
        FrameworkElement element,
        double width,
        double height,
        string assetFileName,
        int zIndex)
    {
        if (!MaotaiAssetManifest.TryGetDescriptor(assetFileName, out var descriptor) ||
            descriptor.Width <= 0.0 ||
            descriptor.Height <= 0.0)
        {
            throw new InvalidOperationException(
                $"Maotai v2 body layout descriptor missing: {assetFileName}");
        }

        var pivotX = descriptor.PivotX / descriptor.Width;
        var pivotY = descriptor.PivotY / descriptor.Height;
        ConfigurePivotedImage(element, width, height, pivotX, pivotY, zIndex);
    }

    private static void ConfigurePivotedImage(
        FrameworkElement element,
        double width,
        double height,
        double pivotX,
        double pivotY,
        int zIndex)
    {
        element.Width                 = width;
        element.Height                = height;
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
