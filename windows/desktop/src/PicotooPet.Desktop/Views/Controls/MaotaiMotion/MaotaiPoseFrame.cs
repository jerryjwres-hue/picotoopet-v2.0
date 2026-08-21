namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>单个骨骼在统一逻辑坐标系中的不可变姿态。</summary>
internal readonly record struct MaotaiBonePose(
    double X,
    double Y,
    double RotationDeg,
    double ScaleX = 1.0,
    double ScaleY = 1.0);

/// <summary>茅台眼睛的离散表情状态。</summary>
internal enum MaotaiEyeState
{
    Open,
    Half,
    Closed,
}

/// <summary>茅台嘴型的离散表情状态。</summary>
internal enum MaotaiMouthState
{
    Smile,
    Tired,
    Annoyed,
    Yawn,
    Tongue,
}

/// <summary>Motion Engine 输出给渲染器的一帧纯值类型数据；帧循环无需创建集合。</summary>
internal readonly record struct MaotaiPoseFrame
{
    private readonly MaotaiMouthState _mouthState;

    public MaotaiBonePose Root { get; init; }

    public MaotaiBonePose Body { get; init; }

    public MaotaiBonePose Chest { get; init; }

    public MaotaiBonePose Head { get; init; }

    public MaotaiBonePose LeftEar { get; init; }

    public MaotaiBonePose RightEar { get; init; }

    public MaotaiBonePose LeftPupil { get; init; }

    public MaotaiBonePose RightPupil { get; init; }

    public MaotaiBonePose FrontLeftUpper { get; init; }

    public MaotaiBonePose FrontLeftLower { get; init; }

    public MaotaiBonePose FrontLeftPaw { get; init; }

    public MaotaiBonePose FrontRightUpper { get; init; }

    public MaotaiBonePose FrontRightLower { get; init; }

    public MaotaiBonePose FrontRightPaw { get; init; }

    public MaotaiBonePose HindLeftUpper { get; init; }

    public MaotaiBonePose HindLeftLower { get; init; }

    public MaotaiBonePose HindLeftPaw { get; init; }

    public MaotaiBonePose HindRightUpper { get; init; }

    public MaotaiBonePose HindRightLower { get; init; }

    public MaotaiBonePose HindRightPaw { get; init; }

    public MaotaiBonePose TailBase { get; init; }

    public MaotaiBonePose TailMid { get; init; }

    public MaotaiBonePose TailTip { get; init; }

    public MaotaiEyeState EyeState { get; init; }

    public MaotaiMouthState MouthState
    {
        get => _mouthState == MaotaiMouthState.Tongue &&
               MotionState != MaotaiMotionState.UserReaction
            ? MaotaiMouthState.Smile
            : _mouthState;
        init => _mouthState = value;
    }

    public MaotaiMotionState MotionState { get; init; }

    // Locomotion envelope   : Motion Engine writes its real normalized speed ratio directly; Renderer never infers travel from posture or facial tension.
    public double LocomotionBlend { get; init; }

    // Expression envelope   : continuous values let overlays blend instead of snapping discrete face images.
    public double YawnProgress { get; init; }

    public double MouthOpenAmount { get; init; }

    public int FacingSign { get; init; }

    // Foot lock telemetry   : value types only; deterministic smoke tests can verify all four support contacts.
    public bool FrontLeftSupport { get; init; }

    public double FrontLeftPawWorldX { get; init; }

    public double FrontLeftPawWorldY { get; init; }

    public bool FrontRightSupport { get; init; }

    public double FrontRightPawWorldX { get; init; }

    public double FrontRightPawWorldY { get; init; }

    public bool HindLeftSupport { get; init; }

    public double HindLeftPawWorldX { get; init; }

    public double HindLeftPawWorldY { get; init; }

    public bool HindRightSupport { get; init; }

    public double HindRightPawWorldX { get; init; }

    public double HindRightPawWorldY { get; init; }

    public double StageX { get; init; }

    public double StageYOffset { get; init; }
}
