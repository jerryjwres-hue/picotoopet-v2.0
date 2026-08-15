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

/// <summary>Motion Engine 输出给渲染器的一帧纯表现数据。</summary>
internal sealed class MaotaiPoseFrame
{
    public MaotaiBonePose Root { get; init; }

    public MaotaiBonePose Body { get; init; }

    public MaotaiBonePose Head { get; init; }

    public MaotaiEyeState EyeState { get; init; } = MaotaiEyeState.Open;

    public MaotaiMouthState MouthState { get; init; } = MaotaiMouthState.Smile;
}
