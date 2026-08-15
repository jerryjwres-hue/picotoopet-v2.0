using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using WpfImage = System.Windows.Controls.Image;

namespace PicotooPet.Desktop.Views.Controls;

public partial class AssistantPetPanel
{
    private readonly WpfImage MaotaiV2TorsoCrouch  = CreateMaotaiV2TorsoVariant("MaotaiV2TorsoCrouch");
    private readonly WpfImage MaotaiV2TorsoStretch = CreateMaotaiV2TorsoVariant("MaotaiV2TorsoStretch");

    private WpfImage MaotaiV2TorsoNeutral => MaotaiV2Torso;

    /// <summary>把两张独立 torso 变体插到 neutral 与 chest/front-leg 之间；仅初始化一次。</summary>
    private void EnsureMaotaiV2TorsoVariantLayers()
    {
        if (MaotaiV2BodyBone.Children.Contains(MaotaiV2TorsoCrouch) &&
            MaotaiV2BodyBone.Children.Contains(MaotaiV2TorsoStretch))
        {
            return;
        }

        var neutralIndex = MaotaiV2BodyBone.Children.IndexOf(MaotaiV2TorsoNeutral);
        if (neutralIndex < 0)
        {
            throw new InvalidOperationException("Maotai v2 neutral torso surface is missing from the body bone.");
        }

        // Layer order        : hind limbs/tail -> neutral/crouch/stretch -> chest/front limbs.
        MaotaiV2BodyBone.Children.Insert(neutralIndex + 1, MaotaiV2TorsoCrouch);
        MaotaiV2BodyBone.Children.Insert(neutralIndex + 2, MaotaiV2TorsoStretch);
    }

    private static WpfImage CreateMaotaiV2TorsoVariant(string name)
    {
        var image = new WpfImage
        {
            Name                  = name,
            Width                 = 78.0,
            Height                = 66.0,
            RenderTransformOrigin = new Point(0.5, 0.55),
            Stretch               = Stretch.Uniform,
            Opacity               = 0.0,
            IsHitTestVisible      = false,
        };

        Canvas.SetLeft(image, -39.0);
        Canvas.SetTop(image, -36.0);
        RenderOptions.SetBitmapScalingMode(image, BitmapScalingMode.HighQuality);
        return image;
    }
}
