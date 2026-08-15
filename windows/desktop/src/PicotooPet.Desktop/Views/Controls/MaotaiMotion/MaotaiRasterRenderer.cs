using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>缓存一个独立光栅骨骼节点及其 Transform；显示帧只写已有对象的数值。</summary>
internal sealed class MaotaiRasterPart
{
    public MaotaiRasterPart(
        FrameworkElement element,
        TranslateTransform translate,
        RotateTransform rotate,
        ScaleTransform? scale = null)
    {
        Element   = element;
        Translate = translate;
        Rotate    = rotate;
        Scale     = scale;
    }

    public FrameworkElement Element { get; }

    public TranslateTransform Translate { get; }

    public RotateTransform Rotate { get; }

    public ScaleTransform? Scale { get; }

    /// <summary>直接更新已有 Freezable；不创建 Storyboard、动画对象或临时集合。</summary>
    public void Apply(
        double x,
        double y,
        double rotationDeg,
        double scaleX = 1.0,
        double scaleY = 1.0)
    {
        Translate.X = x;
        Translate.Y = y;
        Rotate.Angle = rotationDeg;

        if (Scale is not null)
        {
            Scale.ScaleX = scaleX;
            Scale.ScaleY = scaleY;
        }
    }
}

/// <summary>AssistantPetPanel 初始化时一次性收集的 v2 可见图层引用。</summary>
internal sealed class MaotaiRasterVisuals
{
    public required TranslateTransform RootTranslate { get; init; }

    public required ScaleTransform FacingScale { get; init; }

    public required MaotaiRasterPart Body { get; init; }

    public required MaotaiRasterPart Head { get; init; }

    public required MaotaiRasterPart LeftEar { get; init; }

    public required MaotaiRasterPart RightEar { get; init; }

    public required MaotaiRasterPart LeftPupil { get; init; }

    public required MaotaiRasterPart RightPupil { get; init; }

    public required MaotaiRasterPart FrontLeftUpper { get; init; }

    public required MaotaiRasterPart FrontLeftLower { get; init; }

    public required MaotaiRasterPart FrontLeftPaw { get; init; }

    public required MaotaiRasterPart FrontRightUpper { get; init; }

    public required MaotaiRasterPart FrontRightLower { get; init; }

    public required MaotaiRasterPart FrontRightPaw { get; init; }

    public required MaotaiRasterPart HindLeftUpper { get; init; }

    public required MaotaiRasterPart HindLeftLower { get; init; }

    public required MaotaiRasterPart HindLeftPaw { get; init; }

    public required MaotaiRasterPart HindRightUpper { get; init; }

    public required MaotaiRasterPart HindRightLower { get; init; }

    public required MaotaiRasterPart HindRightPaw { get; init; }

    public required MaotaiRasterPart TailBase { get; init; }

    public required MaotaiRasterPart TailMid { get; init; }

    public required MaotaiRasterPart TailTip { get; init; }

    public required Image EyeLeftOpen { get; init; }

    public required Image EyeRightOpen { get; init; }

    public required Image EyeLeftHalf { get; init; }

    public required Image EyeRightHalf { get; init; }

    public required Image EyeLeftClosed { get; init; }

    public required Image EyeRightClosed { get; init; }

    public required Image MouthSmile { get; init; }

    public required Image MouthTired { get; init; }

    public required Image MouthAnnoyed { get; init; }

    public required Image MouthYawn { get; init; }

    public required Image MouthTongue { get; init; }
}

/// <summary>把纯数据 PoseFrame 应用到独立 PNG 骨骼；不包含状态机、IO 或业务逻辑。</summary>
internal sealed class MaotaiRasterRenderer
{
    private readonly MaotaiRasterVisuals _visuals;

    public MaotaiRasterRenderer(MaotaiRasterVisuals visuals)
    {
        _visuals = visuals ?? throw new ArgumentNullException(nameof(visuals));
    }

    /// <summary>每显示帧调用；层级 Transform 与 Motion Engine 的 Body->Head/Leg/Tail 坐标一致。</summary>
    public void Apply(in MaotaiPoseFrame frame)
    {
        _visuals.RootTranslate.X = frame.StageX;
        _visuals.RootTranslate.Y = 0.0;
        _visuals.FacingScale.ScaleX = frame.FacingSign >= 0 ? 1.0 : -1.0;

        _visuals.Body.Apply(
            frame.Body.X,
            frame.Body.Y,
            frame.Body.RotationDeg,
            frame.Body.ScaleX,
            frame.Body.ScaleY);
        _visuals.Head.Apply(
            frame.Head.X,
            frame.Head.Y,
            frame.Head.RotationDeg,
            frame.Head.ScaleX,
            frame.Head.ScaleY);

        _visuals.LeftEar.Apply(
            frame.LeftEar.X,
            frame.LeftEar.Y,
            frame.LeftEar.RotationDeg,
            frame.LeftEar.ScaleX,
            frame.LeftEar.ScaleY);
        _visuals.RightEar.Apply(
            frame.RightEar.X,
            frame.RightEar.Y,
            frame.RightEar.RotationDeg,
            frame.RightEar.ScaleX,
            frame.RightEar.ScaleY);
        _visuals.LeftPupil.Apply(
            frame.LeftPupil.X,
            frame.LeftPupil.Y,
            frame.LeftPupil.RotationDeg);
        _visuals.RightPupil.Apply(
            frame.RightPupil.X,
            frame.RightPupil.Y,
            frame.RightPupil.RotationDeg);

        ApplyBone(_visuals.FrontLeftUpper, frame.FrontLeftUpper);
        ApplyBone(_visuals.FrontLeftLower, frame.FrontLeftLower);
        ApplyBone(_visuals.FrontLeftPaw, frame.FrontLeftPaw);
        ApplyBone(_visuals.FrontRightUpper, frame.FrontRightUpper);
        ApplyBone(_visuals.FrontRightLower, frame.FrontRightLower);
        ApplyBone(_visuals.FrontRightPaw, frame.FrontRightPaw);
        ApplyBone(_visuals.HindLeftUpper, frame.HindLeftUpper);
        ApplyBone(_visuals.HindLeftLower, frame.HindLeftLower);
        ApplyBone(_visuals.HindLeftPaw, frame.HindLeftPaw);
        ApplyBone(_visuals.HindRightUpper, frame.HindRightUpper);
        ApplyBone(_visuals.HindRightLower, frame.HindRightLower);
        ApplyBone(_visuals.HindRightPaw, frame.HindRightPaw);
        ApplyBone(_visuals.TailBase, frame.TailBase);
        ApplyBone(_visuals.TailMid, frame.TailMid);
        ApplyBone(_visuals.TailTip, frame.TailTip);

        ApplyEyeState(frame.EyeState);
        ApplyMouthState(frame.MouthState);
    }

    private static void ApplyBone(
        MaotaiRasterPart part,
        in MaotaiBonePose pose) =>
        part.Apply(
            pose.X,
            pose.Y,
            pose.RotationDeg,
            pose.ScaleX,
            pose.ScaleY);

    private void ApplyEyeState(MaotaiEyeState state)
    {
        var open   = state == MaotaiEyeState.Open ? 1.0 : 0.0;
        var half   = state == MaotaiEyeState.Half ? 1.0 : 0.0;
        var closed = state == MaotaiEyeState.Closed ? 1.0 : 0.0;

        _visuals.EyeLeftOpen.Opacity    = open;
        _visuals.EyeRightOpen.Opacity   = open;
        _visuals.EyeLeftHalf.Opacity    = half;
        _visuals.EyeRightHalf.Opacity   = half;
        _visuals.EyeLeftClosed.Opacity  = closed;
        _visuals.EyeRightClosed.Opacity = closed;
    }

    private void ApplyMouthState(MaotaiMouthState state)
    {
        _visuals.MouthSmile.Opacity   = state == MaotaiMouthState.Smile ? 1.0 : 0.0;
        _visuals.MouthTired.Opacity   = state == MaotaiMouthState.Tired ? 1.0 : 0.0;
        _visuals.MouthAnnoyed.Opacity = state == MaotaiMouthState.Annoyed ? 1.0 : 0.0;
        _visuals.MouthYawn.Opacity    = state == MaotaiMouthState.Yawn ? 1.0 : 0.0;
        _visuals.MouthTongue.Opacity  = state == MaotaiMouthState.Tongue ? 1.0 : 0.0;
    }
}
