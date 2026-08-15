namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>一条腿在本帧的局部骨骼姿态。</summary>
internal readonly record struct MaotaiLegPose(
    MaotaiBonePose Upper,
    MaotaiBonePose Lower,
    MaotaiBonePose Paw,
    double PawWorldX,
    double PawWorldY);

/// <summary>连续时间茅台运动核心；只消费表现输入并产出确定性 PoseFrame。</summary>
internal sealed class MaotaiMotionEngine
{
    private const double WalkRunSpeedReference = 76.0;
    private const double GroundWorldY           = 0.0;

    private readonly MaotaiAnimationGraph _graph = new(MaotaiMotionState.Idle);
    private readonly MaotaiLocomotionController _locomotion;

    private readonly MaotaiSpring _headX       = new(0.0, 0.0, 5.2, 0.88);
    private readonly MaotaiSpring _headY       = new(0.0, 0.0, 5.0, 0.90);
    private readonly MaotaiSpring _headRotate  = new(0.0, 0.0, 4.8, 0.86);
    private readonly MaotaiSpring _leftEar     = new(0.0, 0.0, 4.0, 0.78);
    private readonly MaotaiSpring _rightEar    = new(0.0, 0.0, 4.2, 0.80);
    private readonly MaotaiSpring _tailBase    = new(0.0, 0.0, 4.6, 0.72);
    private readonly MaotaiSpring _tailMid     = new(0.0, 0.0, 3.8, 0.70);
    private readonly MaotaiSpring _tailTip     = new(0.0, 0.0, 3.2, 0.68);

    private readonly double _idlePhaseOffset;

    private MaotaiMotionState _lastDesiredState = MaotaiMotionState.Idle;
    private bool _jumpSequenceActive;
    private double _landingHoldSeconds;
    private double _elapsedSeconds;

    private bool _frontLeftWasSupport;
    private double _frontLeftAnchorWorldX;
    private double _frontLeftAnchorWorldY;

    public MaotaiMotionEngine(int seed, double initialX)
    {
        _locomotion      = new MaotaiLocomotionController(initialX);
        _idlePhaseOffset = ((seed & 1023) / 1024.0) * Math.PI * 2.0;
    }

    public MaotaiMotionState ActiveState => _graph.ActiveState;

    public double PositionX => _locomotion.PositionX;

    /// <summary>按 deltaTime 推进一步；相同 seed 与输入序列必须得到完全相同的输出。</summary>
    public MaotaiPoseFrame Update(
        double deltaTime,
        MaotaiMotionInput input)
    {
        var dt = double.IsFinite(deltaTime)
            ? Math.Clamp(deltaTime, 0.0, 0.05)
            : 0.0;
        _elapsedSeconds += dt;

        var desiredState = MaotaiBehaviorPlanner.Plan(input, _locomotion.PositionX);
        var movementTarget = input.BaseState == MaotaiBaseState.Working
            ? input.WorkAnchorX
            : input.TargetX;

        UpdateAnimationIntent(input, desiredState);
        _graph.Update(dt);

        var executeJump = _jumpSequenceActive &&
            _graph.ActiveState == MaotaiMotionState.JumpAir &&
            _locomotion.IsGrounded;
        var wantsRun = _graph.ActiveState == MaotaiMotionState.Run ||
            (desiredState == MaotaiMotionState.Run && !_jumpSequenceActive);

        _locomotion.Update(
            dt,
            movementTarget,
            wantsRun,
            executeJump,
            input.StageMinX,
            input.StageMaxX);

        if (_locomotion.LandedThisFrame)
        {
            _jumpSequenceActive = false;
            _landingHoldSeconds = 0.20;
            _graph.Request(MaotaiMotionState.Land);
            _lastDesiredState = MaotaiMotionState.Land;
        }

        if (_landingHoldSeconds > 0.0)
        {
            _landingHoldSeconds = Math.Max(0.0, _landingHoldSeconds - dt);
            if (_landingHoldSeconds <= 0.0)
            {
                _graph.Request(desiredState);
                _lastDesiredState = desiredState;
            }
        }

        return BuildPose(input, dt);
    }

    private void UpdateAnimationIntent(
        MaotaiMotionInput input,
        MaotaiMotionState desiredState)
    {
        if (input.WantsJump &&
            !_jumpSequenceActive &&
            _landingHoldSeconds <= 0.0 &&
            _locomotion.IsGrounded)
        {
            _jumpSequenceActive = true;
            _graph.Request(MaotaiMotionState.JumpAir);
            _lastDesiredState = MaotaiMotionState.JumpAir;
            return;
        }

        if (_jumpSequenceActive || _landingHoldSeconds > 0.0)
        {
            return;
        }

        if (desiredState == _lastDesiredState)
        {
            return;
        }

        _graph.Request(desiredState);
        _lastDesiredState = desiredState;
    }

    private MaotaiPoseFrame BuildPose(
        in MaotaiMotionInput input,
        double dt)
    {
        var speedRatio = Math.Clamp(
            Math.Abs(_locomotion.VelocityX) / WalkRunSpeedReference,
            0.0,
            1.0);
        var gaitPhase  = _locomotion.GaitPhase;
        var gaitAngle  = gaitPhase * Math.PI * 2.0;
        var grounded   = _locomotion.IsGrounded;
        var facingSign = _locomotion.FacingSign;

        var bodyBob = grounded
            ? Math.Sin(gaitAngle * 2.0) * (0.55 + (speedRatio * 1.45))
            : 0.0;
        var breathing  = Math.Sin((_elapsedSeconds * 2.1) + _idlePhaseOffset) * 0.32;
        var bodyWorldY = -44.0 + _locomotion.VerticalOffset + bodyBob + breathing;
        var bodyTilt   = -facingSign * speedRatio * 5.4;

        var bodyScaleX = 1.0;
        var bodyScaleY = 1.0;
        if (_graph.ActiveState == MaotaiMotionState.JumpPrep)
        {
            bodyScaleX = 1.045;
            bodyScaleY = 0.925;
        }
        else if (_graph.ActiveState == MaotaiMotionState.Land)
        {
            bodyScaleX = 1.055;
            bodyScaleY = 0.935;
        }

        var pointerX = input.PointerInside
            ? Math.Clamp(input.PointerX, -1.0, 1.0)
            : 0.0;
        var pointerY = input.PointerInside
            ? Math.Clamp(input.PointerY, -1.0, 1.0)
            : 0.0;
        var idleLook = input.PointerInside
            ? 0.0
            : Math.Sin((_elapsedSeconds * 0.82) + _idlePhaseOffset) * 1.15;

        _headX.Step((pointerX * 2.0) + (idleLook * 0.18), dt);
        _headY.Step(pointerY * 1.25, dt);
        _headRotate.Step((pointerX * 7.0) + idleLook - (bodyTilt * 0.22), dt);

        var earGait = Math.Sin(gaitAngle + 0.45) * (0.8 + (speedRatio * 2.3));
        _leftEar.Step((_headRotate.Value * 0.32) + earGait, dt);
        _rightEar.Step((_headRotate.Value * 0.28) - (earGait * 0.82), dt);

        var tailEnergy = input.BaseState switch
        {
            MaotaiBaseState.Offline => 0.12,
            MaotaiBaseState.Error   => 0.18,
            MaotaiBaseState.Working => 0.52,
            _                       => 0.68,
        };
        var tailTarget = Math.Sin((gaitAngle * 1.2) + (_elapsedSeconds * 1.35)) *
            (4.0 + (tailEnergy * 10.0));
        _tailBase.Step(tailTarget, dt);
        _tailMid.Step((_tailBase.Value * 1.08) - (_locomotion.VelocityX * 0.025), dt);
        _tailTip.Step((_tailMid.Value * 1.12) - (_locomotion.VelocityX * 0.018), dt);

        var frontLeft = BuildFrontLeftLeg(
            gaitPhase,
            speedRatio,
            bodyWorldY,
            facingSign,
            grounded);
        var frontRight = BuildFreeLeg(
            Wrap01(gaitPhase + 0.50),
            speedRatio,
            bodyWorldY,
            facingSign,
            shoulderLocalX: 15.5,
            shoulderLocalY: 10.0,
            frontLeg: true);
        var hindLeft = BuildFreeLeg(
            Wrap01(gaitPhase + 0.50),
            speedRatio,
            bodyWorldY,
            facingSign,
            shoulderLocalX: -15.0,
            shoulderLocalY: 12.0,
            frontLeg: false);
        var hindRight = BuildFreeLeg(
            gaitPhase,
            speedRatio,
            bodyWorldY,
            facingSign,
            shoulderLocalX: -17.0,
            shoulderLocalY: 12.0,
            frontLeg: false);

        var eyeState = input.BaseState switch
        {
            MaotaiBaseState.Offline => MaotaiEyeState.Closed,
            MaotaiBaseState.Error   => MaotaiEyeState.Half,
            _                       => MaotaiEyeState.Open,
        };
        var mouthState = input.Interaction switch
        {
            MaotaiInteractionKind.Pat       => MaotaiMouthState.Tongue,
            MaotaiInteractionKind.Paw       => MaotaiMouthState.Tongue,
            MaotaiInteractionKind.Celebrate => MaotaiMouthState.Tongue,
            _ when input.BaseState == MaotaiBaseState.Error   => MaotaiMouthState.Annoyed,
            _ when input.BaseState == MaotaiBaseState.Offline => MaotaiMouthState.Tired,
            _ => MaotaiMouthState.Smile,
        };

        var pupilX = pointerX * 1.9;
        var pupilY = pointerY * 1.1;

        return new MaotaiPoseFrame
        {
            Root                   = new MaotaiBonePose(_locomotion.PositionX, 0.0, 0.0),
            Body                   = new MaotaiBonePose(0.0, bodyWorldY, bodyTilt, bodyScaleX, bodyScaleY),
            Chest                  = new MaotaiBonePose(facingSign * 2.0, -4.0, bodyTilt * 0.22),
            Head                   = new MaotaiBonePose(_headX.Value, -29.0 + _headY.Value, _headRotate.Value),
            LeftEar                = new MaotaiBonePose(-11.0, -20.0, _leftEar.Value),
            RightEar               = new MaotaiBonePose(11.0, -20.0, _rightEar.Value),
            LeftPupil              = new MaotaiBonePose(-6.0 + pupilX, -2.0 + pupilY, 0.0),
            RightPupil             = new MaotaiBonePose(6.0 + pupilX, -2.0 + pupilY, 0.0),
            FrontLeftUpper         = frontLeft.Upper,
            FrontLeftLower         = frontLeft.Lower,
            FrontLeftPaw           = frontLeft.Paw,
            FrontRightUpper        = frontRight.Upper,
            FrontRightLower        = frontRight.Lower,
            FrontRightPaw          = frontRight.Paw,
            HindLeftUpper          = hindLeft.Upper,
            HindLeftLower          = hindLeft.Lower,
            HindLeftPaw            = hindLeft.Paw,
            HindRightUpper         = hindRight.Upper,
            HindRightLower         = hindRight.Lower,
            HindRightPaw           = hindRight.Paw,
            TailBase               = new MaotaiBonePose(-20.0 * facingSign, -10.0, _tailBase.Value),
            TailMid                = new MaotaiBonePose(-11.0 * facingSign, -8.0, _tailMid.Value),
            TailTip                = new MaotaiBonePose(-10.0 * facingSign, -7.0, _tailTip.Value),
            EyeState               = eyeState,
            MouthState             = mouthState,
            MotionState            = _graph.ActiveState,
            FacingSign             = facingSign,
            FrontLeftSupport       = _frontLeftWasSupport,
            FrontLeftPawWorldX     = frontLeft.PawWorldX,
            FrontLeftPawWorldY     = frontLeft.PawWorldY,
            StageX                 = _locomotion.PositionX,
            StageYOffset           = _locomotion.VerticalOffset,
        };
    }

    private MaotaiLegPose BuildFrontLeftLeg(
        double gaitPhase,
        double speedRatio,
        double bodyWorldY,
        int facingSign,
        bool grounded)
    {
        var shoulderLocalX = 17.5 * facingSign;
        var shoulderLocalY = 9.5;
        var stride         = 12.0 + (speedRatio * 13.0);
        var moving         = Math.Abs(_locomotion.VelocityX) > 2.0;
        var support        = grounded && moving && gaitPhase < 0.56;

        double pawWorldX;
        double pawWorldY;

        if (support)
        {
            if (!_frontLeftWasSupport)
            {
                _frontLeftAnchorWorldX = _locomotion.PositionX +
                    shoulderLocalX +
                    (facingSign * stride * 0.34);
                _frontLeftAnchorWorldY = GroundWorldY;
            }

            pawWorldX = _frontLeftAnchorWorldX;
            pawWorldY = _frontLeftAnchorWorldY;
        }
        else
        {
            var swingPhase = gaitPhase < 0.56
                ? 0.0
                : (gaitPhase - 0.56) / 0.44;
            var swingAngle = swingPhase * Math.PI;
            pawWorldX = _locomotion.PositionX +
                shoulderLocalX +
                (facingSign * ((swingPhase * 2.0) - 1.0) * stride * 0.58);
            pawWorldY = grounded
                ? GroundWorldY - (Math.Sin(swingAngle) * (5.0 + (speedRatio * 6.5)))
                : bodyWorldY + 39.0;
        }

        _frontLeftWasSupport = support;
        return SolveLeg(
            shoulderLocalX,
            shoulderLocalY,
            pawWorldX,
            pawWorldY,
            bodyWorldY,
            facingSign,
            frontLeg: true);
    }

    private MaotaiLegPose BuildFreeLeg(
        double phase,
        double speedRatio,
        double bodyWorldY,
        int facingSign,
        double shoulderLocalX,
        double shoulderLocalY,
        bool frontLeg)
    {
        shoulderLocalX *= facingSign;
        var stride      = (frontLeg ? 11.0 : 9.0) + (speedRatio * (frontLeg ? 12.0 : 10.0));
        var phaseAngle  = phase * Math.PI * 2.0;
        var pawWorldX   = _locomotion.PositionX +
            shoulderLocalX +
            (Math.Cos(phaseAngle) * stride * 0.44 * facingSign);
        var lift = _locomotion.IsGrounded
            ? Math.Max(0.0, Math.Sin(phaseAngle)) * (4.0 + (speedRatio * 5.0))
            : 5.0;
        var pawWorldY = _locomotion.IsGrounded
            ? GroundWorldY - lift
            : bodyWorldY + (frontLeg ? 38.0 : 40.0);

        return SolveLeg(
            shoulderLocalX,
            shoulderLocalY,
            pawWorldX,
            pawWorldY,
            bodyWorldY,
            facingSign,
            frontLeg);
    }

    private MaotaiLegPose SolveLeg(
        double shoulderLocalX,
        double shoulderLocalY,
        double pawWorldX,
        double pawWorldY,
        double bodyWorldY,
        int facingSign,
        bool frontLeg)
    {
        var pawLocalX   = pawWorldX - _locomotion.PositionX;
        var pawLocalY   = pawWorldY - bodyWorldY;
        var upperLength = frontLeg ? 27.0 : 25.0;
        var lowerLength = frontLeg ? 26.0 : 25.0;
        var bendSign    = frontLeg ? facingSign : -facingSign;
        var solution = MaotaiIkSolver.SolveTwoBone(
            shoulderLocalX,
            shoulderLocalY,
            upperLength,
            lowerLength,
            pawLocalX,
            pawLocalY,
            bendSign);

        return new MaotaiLegPose(
            new MaotaiBonePose(shoulderLocalX, shoulderLocalY, solution.UpperAngleDeg),
            new MaotaiBonePose(solution.JointX, solution.JointY, solution.LowerAngleDeg),
            new MaotaiBonePose(pawLocalX, pawLocalY, -solution.LowerAngleDeg * 0.08),
            pawWorldX,
            pawWorldY);
    }

    private static double Wrap01(double value)
    {
        value %= 1.0;
        return value < 0.0
            ? value + 1.0
            : value;
    }
}
