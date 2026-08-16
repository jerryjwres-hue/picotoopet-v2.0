using System.Windows;
using System.Windows.Media;
using WpfImage = System.Windows.Controls.Image;
using WpfPanel = System.Windows.Controls.Panel;

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
        Translate.X  = x;
        Translate.Y  = y;
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

    public required WpfImage TorsoNeutral { get; init; }

    public required WpfImage TorsoCrouch { get; init; }

    public required WpfImage TorsoStretch { get; init; }

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

    public required WpfImage EyeLeftOpen { get; init; }

    public required WpfImage EyeRightOpen { get; init; }

    public required WpfImage EyeLeftHalf { get; init; }

    public required WpfImage EyeRightHalf { get; init; }

    public required WpfImage EyeLeftClosed { get; init; }

    public required WpfImage EyeRightClosed { get; init; }

    public required WpfImage MouthSmile { get; init; }

    public required WpfImage MouthTired { get; init; }

    public required WpfImage MouthAnnoyed { get; init; }

    public required WpfImage MouthYawn { get; init; }

    public required WpfImage MouthTongue { get; init; }
}

/// <summary>把纯数据 PoseFrame 应用到独立 PNG 骨骼；不包含状态机、IO 或业务逻辑。</summary>
internal sealed class MaotaiRasterRenderer
{
    private readonly MaotaiRasterVisuals _visuals;

    public MaotaiRasterRenderer(MaotaiRasterVisuals visuals)
    {
        _visuals = visuals ?? throw new ArgumentNullException(nameof(visuals));

        // Body/face binding is asset-specific, so calibrate existing WPF layers once here rather than
        // leaking pixel offsets into the pure Motion Engine or reallocating anything per display frame.
        var bodyPanel = _visuals.TorsoNeutral.Parent as WpfPanel
            ?? throw new InvalidOperationException("Maotai v2 torso layers are not attached to the body panel.");
        MaotaiRasterBodyLayout.Configure(bodyPanel);

        var headPanel = _visuals.EyeLeftOpen.Parent as WpfPanel
            ?? throw new InvalidOperationException("Maotai v2 face layers are not attached to the head panel.");
        MaotaiRasterFaceLayout.Configure(headPanel);
    }

    /// <summary>每显示帧调用；层级 Transform 与 Motion Engine 的 Body->Head/Leg/Tail 坐标一致。</summary>
    public void Apply(in MaotaiPoseFrame frame)
    {
        _visuals.RootTranslate.X     = frame.StageX;
        _visuals.RootTranslate.Y     = 0.0;
        _visuals.FacingScale.ScaleX = frame.FacingSign >= 0 ? 1.0 : -1.0;

        _visuals.Body.Apply(
            frame.Body.X,
            frame.Body.Y,
            frame.Body.RotationDeg,
            frame.Body.ScaleX,
            frame.Body.ScaleY);

        // Torso silhouette : blend independent neutral/crouch/stretch art from the same continuous body pose.
        var torsoBlend = MaotaiTorsoVariantBlend.FromScaleY(frame.Body.ScaleY);
        _visuals.TorsoNeutral.Opacity = torsoBlend.Neutral;
        _visuals.TorsoCrouch.Opacity  = torsoBlend.Crouch;
        _visuals.TorsoStretch.Opacity = torsoBlend.Stretch;

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
            MaotaiRasterFaceLayout.CalibratePupilX(frame.LeftPupil.X, isLeft: true),
            MaotaiRasterFaceLayout.CalibratePupilY(frame.LeftPupil.Y),
            frame.LeftPupil.RotationDeg);
        _visuals.RightPupil.Apply(
            MaotaiRasterFaceLayout.CalibratePupilX(frame.RightPupil.X, isLeft: false),
            MaotaiRasterFaceLayout.CalibratePupilY(frame.RightPupil.Y),
            frame.RightPupil.RotationDeg);

        ApplyLegBone(_visuals.FrontLeftUpper, frame.FrontLeftUpper);
        ApplyLegBone(_visuals.FrontLeftLower, frame.FrontLeftLower);
        ApplyBone(_visuals.FrontLeftPaw, frame.FrontLeftPaw);
        ApplyLegBone(_visuals.FrontRightUpper, frame.FrontRightUpper);
        ApplyLegBone(_visuals.FrontRightLower, frame.FrontRightLower);
        ApplyBone(_visuals.FrontRightPaw, frame.FrontRightPaw);
        ApplyLegBone(_visuals.HindLeftUpper, frame.HindLeftUpper);
        ApplyLegBone(_visuals.HindLeftLower, frame.HindLeftLower);
        ApplyBone(_visuals.HindLeftPaw, frame.HindLeftPaw);
        ApplyLegBone(_visuals.HindRightUpper, frame.HindRightUpper);
        ApplyLegBone(_visuals.HindRightLower, frame.HindRightLower);
        ApplyBone(_visuals.HindRightPaw, frame.HindRightPaw);
        ApplyBone(_visuals.TailBase, frame.TailBase);
        ApplyBone(_visuals.TailMid, frame.TailMid);
        ApplyBone(_visuals.TailTip, frame.TailTip);

        ApplyFace(frame);
    }

    private static void ApplyLegBone(
        MaotaiRasterPart part,
        in MaotaiBonePose pose) =>
        part.Apply(
            pose.X,
            pose.Y,
            MaotaiRasterAxis.LegRotationFromIkDegrees(pose.RotationDeg),
            pose.ScaleX,
            pose.ScaleY);

    private static void ApplyBone(
        MaotaiRasterPart part,
        in MaotaiBonePose pose) =>
        part.Apply(
            pose.X,
            pose.Y,
            pose.RotationDeg,
            pose.ScaleX,
            pose.ScaleY);

    private void ApplyFace(in MaotaiPoseFrame frame)
    {
        if (frame.MotionState == MaotaiMotionState.Yawn)
        {
            var progress = Math.Clamp(frame.YawnProgress, 0.0, 1.0);
            var opening  = Math.Clamp(frame.MouthOpenAmount, 0.0, 1.0);
            var baseFace = 1.0 - opening;
            var tired    = baseFace * (1.0 - progress);
            var smile    = baseFace * progress;

            ApplyEyeOpacities(
                open: smile,
                half: tired,
                closed: opening);
            ApplyMouthOpacities(
                smile: smile,
                tired: tired,
                annoyed: 0.0,
                yawn: opening,
                tongue: 0.0);
            return;
        }

        ApplyEyeState(frame.EyeState);
        ApplyMouthState(frame.MouthState);
    }

    private void ApplyEyeState(MaotaiEyeState state)
    {
        var open   = state == MaotaiEyeState.Open ? 1.0 : 0.0;
        var half   = state == MaotaiEyeState.Half ? 1.0 : 0.0;
        var closed = state == MaotaiEyeState.Closed ? 1.0 : 0.0;
        ApplyEyeOpacities(open, half, closed);
    }

    private void ApplyEyeOpacities(
        double open,
        double half,
        double closed)
    {
        _visuals.EyeLeftOpen.Opacity    = open;
        _visuals.EyeRightOpen.Opacity   = open;
        _visuals.EyeLeftHalf.Opacity    = half;
        _visuals.EyeRightHalf.Opacity   = half;
        _visuals.EyeLeftClosed.Opacity  = closed;
        _visuals.EyeRightClosed.Opacity = closed;
    }

    private void ApplyMouthState(MaotaiMouthState state)
    {
        ApplyMouthOpacities(
            smile: state == MaotaiMouthState.Smile ? 1.0 : 0.0,
            tired: state == MaotaiMouthState.Tired ? 1.0 : 0.0,
            annoyed: state == MaotaiMouthState.Annoyed ? 1.0 : 0.0,
            yawn: state == MaotaiMouthState.Yawn ? 1.0 : 0.0,
            tongue: state == MaotaiMouthState.Tongue ? 1.0 : 0.0);
    }

    private void ApplyMouthOpacities(
        double smile,
        double tired,
        double annoyed,
        double yawn,
        double tongue)
    {
        _visuals.MouthSmile.Opacity   = smile;
        _visuals.MouthTired.Opacity   = tired;
        _visuals.MouthAnnoyed.Opacity = annoyed;
        _visuals.MouthYawn.Opacity    = yawn;
        _visuals.MouthTongue.Opacity  = tongue;
    }
}
