namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>茅台 v2 单个独立光栅部件的逻辑布局元数据。</summary>
internal readonly record struct MaotaiAssetDescriptor(
    string FileName,
    double Width,
    double Height,
    double PivotX,
    double PivotY,
    int ZIndex,
    double JointOverlapPixels);

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
    public static bool IsKnownAsset(string fileName) => TryGetDescriptor(fileName, out _);

    /// <summary>返回经过冻结的尺寸、Pivot 与隐藏重叠区合同；渲染与资产检查共用同一真相源。</summary>
    public static bool TryGetDescriptor(
        string fileName,
        out MaotaiAssetDescriptor descriptor)
    {
        descriptor = default;
        if (string.IsNullOrWhiteSpace(fileName) ||
            fileName.Contains("..", StringComparison.Ordinal) ||
            fileName.Contains('/') ||
            fileName.Contains('\\'))
        {
            return false;
        }

        descriptor = fileName switch
        {
            TorsoNeutral   => D(TorsoNeutral, 92, 78, 46, 41, 20, 20),
            TorsoCrouch    => D(TorsoCrouch, 96, 72, 48, 39, 20, 20),
            TorsoStretch   => D(TorsoStretch, 90, 86, 45, 45, 20, 20),
            ChestFur       => D(ChestFur, 62, 52, 31, 18, 34, 16),
            Head           => D(Head, 78, 70, 39, 42, 60, 20),
            Muzzle         => D(Muzzle, 46, 34, 23, 15, 76, 14),
            EarLeft        => D(EarLeft, 34, 44, 18, 38, 58, 18),
            EarRight       => D(EarRight, 34, 44, 16, 38, 58, 18),
            EyeLeftOpen    => D(EyeLeftOpen, 24, 20, 12, 10, 80, 12),
            EyeRightOpen   => D(EyeRightOpen, 24, 20, 12, 10, 80, 12),
            EyeLeftHalf    => D(EyeLeftHalf, 24, 16, 12, 8, 80, 12),
            EyeRightHalf   => D(EyeRightHalf, 24, 16, 12, 8, 80, 12),
            EyeLeftClosed  => D(EyeLeftClosed, 24, 12, 12, 6, 80, 12),
            EyeRightClosed => D(EyeRightClosed, 24, 12, 12, 6, 80, 12),
            PupilLeft      => D(PupilLeft, 10, 10, 5, 5, 82, 12),
            PupilRight     => D(PupilRight, 10, 10, 5, 5, 82, 12),
            BrowLeft       => D(BrowLeft, 24, 10, 12, 5, 84, 12),
            BrowRight      => D(BrowRight, 24, 10, 12, 5, 84, 12),
            MouthSmile     => D(MouthSmile, 30, 22, 15, 9, 86, 12),
            MouthTired     => D(MouthTired, 30, 20, 15, 9, 86, 12),
            MouthAnnoyed   => D(MouthAnnoyed, 30, 18, 15, 8, 86, 12),
            MouthYawn      => D(MouthYawn, 34, 34, 17, 11, 86, 12),
            MouthTongue    => D(MouthTongue, 34, 30, 17, 10, 86, 12),
            FrontLeftUpper  => D(FrontLeftUpper, 34, 46, 17, 12, 42, 20),
            FrontLeftLower  => D(FrontLeftLower, 32, 44, 16, 12, 44, 20),
            FrontLeftPaw    => D(FrontLeftPaw, 38, 28, 19, 12, 46, 18),
            FrontRightUpper => D(FrontRightUpper, 34, 46, 17, 12, 40, 20),
            FrontRightLower => D(FrontRightLower, 32, 44, 16, 12, 42, 20),
            FrontRightPaw   => D(FrontRightPaw, 38, 28, 19, 12, 44, 18),
            HindLeftUpper   => D(HindLeftUpper, 38, 44, 19, 12, 30, 20),
            HindLeftLower   => D(HindLeftLower, 36, 42, 18, 12, 32, 20),
            HindLeftPaw     => D(HindLeftPaw, 42, 30, 21, 13, 34, 18),
            HindRightUpper  => D(HindRightUpper, 38, 44, 19, 12, 28, 20),
            HindRightLower  => D(HindRightLower, 36, 42, 18, 12, 30, 20),
            HindRightPaw    => D(HindRightPaw, 42, 30, 21, 13, 32, 18),
            TailBase        => D(TailBase, 48, 42, 38, 22, 18, 22),
            TailMid         => D(TailMid, 46, 38, 36, 20, 17, 22),
            TailTip         => D(TailTip, 42, 34, 34, 18, 16, 18),
            HeadphoneBand   => D(HeadphoneBand, 72, 48, 36, 32, 88, 16),
            HeadphoneLeft   => D(HeadphoneLeft, 28, 34, 18, 17, 90, 14),
            HeadphoneRight  => D(HeadphoneRight, 28, 34, 10, 17, 90, 14),
            Laptop          => D(Laptop, 92, 58, 46, 52, 100, 12),
            Drink           => D(Drink, 34, 50, 17, 44, 102, 12),
            Shadow          => D(Shadow, 112, 26, 56, 13, 4, 12),
            _               => default,
        };

        return !string.IsNullOrEmpty(descriptor.FileName);
    }

    private static MaotaiAssetDescriptor D(
        string fileName,
        double width,
        double height,
        double pivotX,
        double pivotY,
        int zIndex,
        double overlapPixels) =>
        new(fileName, width, height, pivotX, pivotY, zIndex, overlapPixels);
}
