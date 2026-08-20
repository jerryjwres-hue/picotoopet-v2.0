using System.Text;
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
        ArgumentNullException.ThrowIfNull(element);
        ApplyManifestPivotFromElementName(element);

        var effectiveScale = scale;
        if (effectiveScale is null)
        {
            // Transform ownership : add one cached ScaleTransform at initialization; render frames only mutate values.
            effectiveScale = new ScaleTransform();
            var group       = new TransformGroup();
            group.Children.Add(effectiveScale);
            group.Children.Add(rotate);
            group.Children.Add(translate);
            element.RenderTransform = group;
        }

        Element   = element;
        Translate = translate;
        Rotate    = rotate;
        Scale     = effectiveScale;
    }

    /// <summary>
    /// 为没有预声明 Transform 的独立光栅层一次性建立 TransformGroup；Pivot 直接来自 manifest，
    /// 避免 Chest 这类真正独立部件在运行时退化成硬编码中心点。
    /// </summary>
    public MaotaiRasterPart(
        FrameworkElement element,
        string assetFileName)
    {
        ApplyManifestPivot(element, assetFileName);

        var scale     = new ScaleTransform();
        var rotate    = new RotateTransform();
        var translate = new TranslateTransform();
        var group     = new TransformGroup();
        group.Children.Add(scale);
        group.Children.Add(rotate);
        group.Children.Add(translate);

        element.RenderTransform = group;

        Element   = element;
        Translate = translate;
        Rotate    = rotate;
        Scale     = scale;
    }

    private static void ApplyManifestPivotFromElementName(FrameworkElement element)
    {
        if (element is not WpfImage)
        {
            return;
        }

        const string prefix = "MaotaiV2";
        var elementName = element.Name;
        if (string.IsNullOrWhiteSpace(elementName) ||
            !elementName.StartsWith(prefix, StringComparison.Ordinal) ||
            elementName.Length <= prefix.Length)
        {
            return;
        }

        var logicalName = elementName.AsSpan(prefix.Length);
        var builder = new StringBuilder(logicalName.Length + 8);
        for (var index = 0; index < logicalName.Length; index++)
        {
            var value = logicalName[index];
            if (index > 0 && char.IsUpper(value))
            {
                builder.Append('_');
            }

            builder.Append(char.ToLowerInvariant(value));
        }

        builder.Append(".png");
        ApplyManifestPivot(element, builder.ToString());
    }

    private static void ApplyManifestPivot(
        FrameworkElement element,
        string assetFileName)
    {
        ArgumentNullException.ThrowIfNull(element);
        if (!MaotaiAssetManifest.TryGetDescriptor(assetFileName, out var descriptor) ||
            descriptor.Width <= 0.0 ||
            descriptor.Height <= 0.0)
        {
            throw new InvalidOperationException($"Maotai v2 asset descriptor missing: {assetFileName}");
        }

        element.RenderTransformOrigin = new System.Windows.Point(
            descriptor.PivotX / descriptor.Width,
            descriptor.PivotY / descriptor.Height);
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

    public required MaotaiRasterPart Chest { get; init; }

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

    public required WpfImage Laptop { get; init; }

    public required WpfImage Drink { get; init; }
}

/// <summary>把纯数据 PoseFrame 应用到独立 PNG 骨骼；不包含状态机、IO 或业务逻辑。</summary>
internal sealed class MaotaiRasterRenderer
{
    private readonly MaotaiRasterVisuals _visuals;
    private readonly WpfImage _headphoneBand;
    private readonly WpfImage _headphoneLeft;
    private readonly WpfImage _headphoneRight;

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
        _headphoneBand  = RequireNamedImage(headPanel, "MaotaiV2HeadphoneBand");
        _headphoneLeft  = RequireNamedImage(headPanel, "MaotaiV2HeadphoneLeft");
        _headphoneRight = RequireNamedImage(headPanel, "MaotaiV2HeadphoneRight");
    }

    /// <summary>每显示帧调用；层级 Transform 与 Motion Engine 的 Body->Chest/Head/Leg/Tail 坐标一致。</summary>
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

        ApplyBone(_visuals.Chest, frame.Chest);

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

        ApplyContinuousLeg(
            _visuals.FrontLeftUpper,
            _visuals.FrontLeftLower,
            frame.FrontLeftUpper,
            frame.FrontLeftPaw,
            visualRootYOffset: -10.0,
            maxScaleY: 1.44);
        ApplyFrontPaw(_visuals.FrontLeftPaw, frame.FrontLeftPaw, frame.MotionState);
        ApplyContinuousLeg(
            _visuals.FrontRightUpper,
            _visuals.FrontRightLower,
            frame.FrontRightUpper,
            frame.FrontRightPaw,
            visualRootYOffset: -10.0,
            maxScaleY: 1.44);
        ApplyFrontPaw(_visuals.FrontRightPaw, frame.FrontRightPaw, frame.MotionState);
        ApplyContinuousLeg(_visuals.HindLeftUpper, _visuals.HindLeftLower, frame.HindLeftUpper, frame.HindLeftPaw);
        ApplyBone(_visuals.HindLeftPaw, frame.HindLeftPaw);
        ApplyContinuousLeg(_visuals.HindRightUpper, _visuals.HindRightLower, frame.HindRightUpper, frame.HindRightPaw);
        ApplyBone(_visuals.HindRightPaw, frame.HindRightPaw);
        ApplyBone(_visuals.TailBase, frame.TailBase);
        ApplyBone(_visuals.TailMid, frame.TailMid);
        ApplyBone(_visuals.TailTip, frame.TailTip);

        ApplyPoseCohesion(frame.MotionState);
        ApplyWorkProps(frame.MotionState);
        ApplyFace(frame);
    }

    private static WpfImage RequireNamedImage(WpfPanel panel, string name)
    {
        foreach (var child in panel.Children)
        {
            if (child is WpfImage image &&
                string.Equals(image.Name, name, StringComparison.Ordinal))
            {
                return image;
            }
        }

        throw new InvalidOperationException($"Maotai v2 face layer missing: {name}");
    }

    private static void ApplyContinuousLeg(
        MaotaiRasterPart upper,
        MaotaiRasterPart lower,
        in MaotaiBonePose upperPose,
        in MaotaiBonePose pawPose,
        double visualRootYOffset = 0.0,
        double maxScaleY = 1.30)
    {
        var visualRootY = upperPose.Y + visualRootYOffset;
        var dx          = pawPose.X - upperPose.X;
        var dy          = pawPose.Y - visualRootY;
        var distance    = Math.Sqrt((dx * dx) + (dy * dy));
        var angleDeg    = Math.Atan2(dy, dx) * 180.0 / Math.PI;

        // Visual root       : front-leg art starts higher inside torso fur; Motion Engine shoulder/foot-lock coordinates stay untouched.
        // Visual reach      : use the post-pivot PNG reach and overlap the paw by a few pixels so no white socket ring remains visible.
        var pivotY      = upper.Element.RenderTransformOrigin.Y;
        var visualReach = Math.Max(1.0, upper.Element.Height * (1.0 - pivotY));
        var scaleY      = Math.Clamp((distance + 4.0) / visualReach, 0.72, maxScaleY);
        upper.Apply(
            upperPose.X,
            visualRootY,
            MaotaiRasterAxis.LegRotationFromIkDegrees(angleDeg),
            scaleX: 0.86,
            scaleY: scaleY);

        lower.Element.Opacity = 0.0;
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

    private static void ApplyFrontPaw(
        MaotaiRasterPart part,
        in MaotaiBonePose pose,
        MaotaiMotionState state)
    {
        var movingFrontView = state is MaotaiMotionState.Walk or MaotaiMotionState.Run;

        // Contact pivot      : position/rotation remain the exact Motion Engine output, so foot-lock physics are untouched.
        // Fur footprint      : narrow only the displayed moving paw around its existing pivot to stop front-view sprite stacking.
        part.Apply(
            pose.X,
            pose.Y,
            pose.RotationDeg,
            scaleX: pose.ScaleX * (movingFrontView ? 0.76 : 1.0),
            scaleY: pose.ScaleY);
    }

    private void ApplyPoseCohesion(MaotaiMotionState state)
    {
        // Folded-pose occlusion : work/rest poses tuck the long limb silhouettes behind the plush torso.
        // Front-view locomotion : rear limbs stay behind the torso/front pair so no detached side paw can pop out.
        var hideFrontUpper = state is
            MaotaiMotionState.WorkSettle or
            MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover or
            MaotaiMotionState.LieDown or
            MaotaiMotionState.Sleep or
            MaotaiMotionState.Wake or
            MaotaiMotionState.GetUp;
        var movingFrontView = state is MaotaiMotionState.Walk or MaotaiMotionState.Run;
        var frontUpperOpacity = hideFrontUpper ? 0.0 : 1.0;
        var rearUpperOpacity  = hideFrontUpper || movingFrontView ? 0.0 : 1.0;

        _visuals.FrontLeftUpper.Element.Opacity  = frontUpperOpacity;
        _visuals.FrontRightUpper.Element.Opacity = frontUpperOpacity;
        _visuals.HindLeftUpper.Element.Opacity   = rearUpperOpacity;
        _visuals.HindRightUpper.Element.Opacity  = rearUpperOpacity;

        _visuals.FrontLeftLower.Element.Opacity  = 0.0;
        _visuals.FrontRightLower.Element.Opacity = 0.0;
        _visuals.HindLeftLower.Element.Opacity   = 0.0;
        _visuals.HindRightLower.Element.Opacity  = 0.0;

        _visuals.FrontLeftPaw.Element.Opacity  = 1.0;
        _visuals.FrontRightPaw.Element.Opacity = 1.0;
        _visuals.HindLeftPaw.Element.Opacity   = movingFrontView ? 0.0 : 1.0;
        _visuals.HindRightPaw.Element.Opacity  = movingFrontView ? 0.0 : 1.0;
    }

    private void ApplyWorkProps(MaotaiMotionState state)
    {
        var visible = state is
            MaotaiMotionState.WorkApproach or
            MaotaiMotionState.WorkSettle or
            MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover;
        var opacity = visible ? 1.0 : 0.0;
        _visuals.Laptop.Opacity = opacity;
        _visuals.Drink.Opacity  = opacity;
        _headphoneBand.Opacity  = opacity;
        _headphoneLeft.Opacity  = opacity;
        _headphoneRight.Opacity = opacity;
    }

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

        var pupilOpacity = MaotaiEyeLayerOpacity.PupilFromOpenWeight(open);
        _visuals.LeftPupil.Element.Opacity  = pupilOpacity;
        _visuals.RightPupil.Element.Opacity = pupilOpacity;
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
