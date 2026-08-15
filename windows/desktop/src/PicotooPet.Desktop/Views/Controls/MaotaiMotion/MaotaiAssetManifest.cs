namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>茅台 v2 单个独立光栅部件的逻辑布局元数据。</summary>
internal readonly record struct MaotaiAssetDescriptor(
    string FileName,
    double Width,
    double Height,
    double PivotX,
    double PivotY,
    int ZIndex);

/// <summary>固定应用 UI 资产白名单；禁止路径穿越、目录扫描和任意用户文件加载。</summary>
internal static class MaotaiAssetManifest
{
    public const string TorsoNeutral   = "torso_neutral.png";
    public const string TorsoCrouch    = "torso_crouch.png";
    public const string TorsoStretch   = "torso_stretch.png";
    public const string ChestFur       = "chest_fur.png";
    public const string Head           = "head.png";
    public const string EarLeft        = "ear_left.png";
    public const string EarRight       = "ear_right.png";
    public const string EyeLeftOpen    = "eye_left_open.png";
    public const string EyeRightOpen   = "eye_right_open.png";
    public const string EyeLeftHalf    = "eye_left_half.png";
    public const string EyeRightHalf   = "eye_right_half.png";
    public const string EyeLeftClosed  = "eye_left_closed.png";
    public const string EyeRightClosed = "eye_right_closed.png";
    public const string PupilLeft      = "pupil_left.png";
    public const string PupilRight     = "pupil_right.png";
    public const string BrowLeft       = "brow_left.png";
    public const string BrowRight      = "brow_right.png";
    public const string Muzzle         = "muzzle.png";
    public const string MouthSmile     = "mouth_smile.png";
    public const string MouthTired     = "mouth_tired.png";
    public const string MouthAnnoyed   = "mouth_annoyed.png";
    public const string MouthYawn      = "mouth_yawn.png";
    public const string MouthTongue    = "mouth_tongue.png";

    public const string FrontLeftUpper  = "front_left_upper.png";
    public const string FrontLeftLower  = "front_left_lower.png";
    public const string FrontLeftPaw    = "front_left_paw.png";
    public const string FrontRightUpper = "front_right_upper.png";
    public const string FrontRightLower = "front_right_lower.png";
    public const string FrontRightPaw   = "front_right_paw.png";
    public const string HindLeftUpper   = "hind_left_upper.png";
    public const string HindLeftLower   = "hind_left_lower.png";
    public const string HindLeftPaw     = "hind_left_paw.png";
    public const string HindRightUpper  = "hind_right_upper.png";
    public const string HindRightLower  = "hind_right_lower.png";
    public const string HindRightPaw    = "hind_right_paw.png";

    public const string TailBase = "tail_base.png";
    public const string TailMid  = "tail_mid.png";
    public const string TailTip  = "tail_tip.png";

    public const string HeadphoneBand  = "headphone_band.png";
    public const string HeadphoneLeft  = "headphone_left.png";
    public const string HeadphoneRight = "headphone_right.png";
    public const string Laptop         = "laptop.png";
    public const string Drink          = "drink.png";
    public const string Shadow         = "shadow.png";

    /// <summary>只接受固定文件名，不接受任何目录、相对路径或扩展资产。</summary>
    public static bool IsKnownAsset(string fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName) ||
            fileName.Contains("..", StringComparison.Ordinal) ||
            fileName.Contains('/') ||
            fileName.Contains('\\'))
        {
            return false;
        }

        return fileName is
            TorsoNeutral
            or TorsoCrouch
            or TorsoStretch
            or ChestFur
            or Head
            or EarLeft
            or EarRight
            or EyeLeftOpen
            or EyeRightOpen
            or EyeLeftHalf
            or EyeRightHalf
            or EyeLeftClosed
            or EyeRightClosed
            or PupilLeft
            or PupilRight
            or BrowLeft
            or BrowRight
            or Muzzle
            or MouthSmile
            or MouthTired
            or MouthAnnoyed
            or MouthYawn
            or MouthTongue
            or FrontLeftUpper
            or FrontLeftLower
            or FrontLeftPaw
            or FrontRightUpper
            or FrontRightLower
            or FrontRightPaw
            or HindLeftUpper
            or HindLeftLower
            or HindLeftPaw
            or HindRightUpper
            or HindRightLower
            or HindRightPaw
            or TailBase
            or TailMid
            or TailTip
            or HeadphoneBand
            or HeadphoneLeft
            or HeadphoneRight
            or Laptop
            or Drink
            or Shadow;
    }
}
