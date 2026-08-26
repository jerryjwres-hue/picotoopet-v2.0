namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>一条腿在本帧的局部骨骼姿态。</summary>
internal readonly record struct MaotaiLegPose(
    MaotaiBonePose Upper,
    MaotaiBonePose Lower,
    MaotaiBonePose Paw,
    double PawWorldX,
    double PawWorldY,
    bool IsSupport);

/// <summary>单只脚掌的支撑相锁定状态；只保存数值，不产生帧级分配。</summary>
internal struct MaotaiFootLockState
{
    public bool WasSupport;

    public double AnchorWorldX;

    public double AnchorWorldY;
}

/// <summary>连续时间茅台运动核心；只消费表现输入并产出确定性 PoseFrame。</summary>
internal sealed class MaotaiMotionEngine
{
    private const double WalkRunSpeedReference  = 76.0;
    private const double GroundWorldY            = 0.0;
    private const double YawnEnvelopeSeconds     = 1.05;
    private const double FrontLegUpperLength     = 19.0;
    private const double FrontLegLowerLength     = 18.0;
    private const double HindLegUpperLength      = 19.0;
    private const double HindLegLowerLength      = 18.0;
    private const double StandingRelaxSpeedRatio = 0.18;
    private const double SupportPhase            = 0.45;

    private readonly MaotaiAnimationGraph _graph = new(MaotaiMotionState.Idle);
    private readonly MaotaiLocomotionController _locomotion;

    private readonly MaotaiSpring _headX      = new(0.0, 0.0, 5.2, 0.88);
    private readonly MaotaiSpring _headY      = new(0.0, 0.0, 5.0, 0.90);
    private readonly MaotaiSpring _headRotate = new(0.0, 0.0, 4.8, 0.86);
    private readonly MaotaiSpring _leftEar    = new(0.0, 0.0, 4.0, 0.78);
    private readonly MaotaiSpring _rightEar   = new(0.0, 0.0, 4.2, 0.80);
    private readonly MaotaiSpring _tailBase   = new(0.0, 0.0, 4.6, 0.72);
    private readonly MaotaiSpring _tailMid    = new(0.0, 0.0, 3.8, 0.70);
    private readonly MaotaiSpring _tailTip    = new(0.0, 0.0, 3.2, 0.68);

    private readonly double _idlePhaseOffset;

    private MaotaiFootLockState _frontLeftLock;
    private MaotaiFootLockState _frontRightLock;
    private MaotaiFootLockState _hindLeftLock;
    private MaotaiFootLockState _hindRightLock;

    private MaotaiMotionState _lastDesiredState = MaotaiMotionState.Idle;
    private MaotaiMotionState _poseState         = MaotaiMotionState.Idle;
    private MaotaiInteractionKind _deferredInteraction = MaotaiInteractionKind.None;
    private bool _jumpSequenceActive;
    private double _landingHoldSeconds;
    private double _elapsedSeconds;
    private double _stateElapsedSeconds;
    private double _typingPhaseRadians;
    private double _lastYawnProgress;
    private double _lastWorkSettleBlend;
    private double _lastTiredBlend;
    private double _lastAnnoyedBlend;

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

        input = ResolveDeferredInteraction(input);
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

        if (input.Interaction == MaotaiInteractionKind.Drag)
        {
            _locomotion.Hold(input.StageMinX, input.StageMaxX);
        }
        else
        {
            _locomotion.Update(
                dt,
                movementTarget,
                wantsRun,
                executeJump,
                input.StageMinX,
                input.StageMaxX);
        }

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

        UpdateStateClock(dt);
        var frame = BuildPose(input, dt);
        CompleteDeferredInteractionIfReady();
        return frame;
    }

    /// <summary>保留已接受的一次性互动，直到必须的 Wake/GetUp 姿态链完成。</summary>
    private MaotaiMotionInput ResolveDeferredInteraction(MaotaiMotionInput input)
    {
        // Strong state         : real Offline/Error authority always cancels cosmetic deferred feedback.
        if (input.BaseState is MaotaiBaseState.Offline or MaotaiBaseState.Error)
        {
            _deferredInteraction = MaotaiInteractionKind.None;
            return input;
        }

        // Direct interaction   : Drag/PointerObserve must follow the latest raw input instead of a stale click latch.
        if (input.Interaction != MaotaiInteractionKind.None &&
            !IsDeferredReactionInteraction(input.Interaction))
        {
            _deferredInteraction = MaotaiInteractionKind.None;
            return input;
        }

        // Accepted click       : keep Pat/Paw/Celebrate alive only when a mandatory rest-transition delays UserReaction.
        if (IsDeferredReactionInteraction(input.Interaction) &&
            (_deferredInteraction != MaotaiInteractionKind.None ||
             RequiresDeferredUserReaction(_graph.ActiveState)))
        {
            _deferredInteraction = input.Interaction;
        }

        return _deferredInteraction != MaotaiInteractionKind.None &&
               input.Interaction == MaotaiInteractionKind.None
            ? input with { Interaction = _deferredInteraction }
            : input;
    }

    /// <summary>只在完整 UserReaction 过渡可见后释放一次性交互，让最新基础状态自然接管。</summary>
    private void CompleteDeferredInteractionIfReady()
    {
        if (_deferredInteraction != MaotaiInteractionKind.None &&
            _graph.ActiveState == MaotaiMotionState.UserReaction &&
            !_graph.IsTransitioning)
        {
            _deferredInteraction = MaotaiInteractionKind.None;
        }
    }

    private static bool IsDeferredReactionInteraction(MaotaiInteractionKind interaction) =>
        interaction is MaotaiInteractionKind.Pat or
            MaotaiInteractionKind.Paw or
            MaotaiInteractionKind.Celebrate;

    private static bool RequiresDeferredUserReaction(MaotaiMotionState state) =>
        state is MaotaiMotionState.Sleep or
            MaotaiMotionState.Wake or
            MaotaiMotionState.LieDown or
            MaotaiMotionState.GetUp;

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

    private void UpdateStateClock(double dt)
    {
        if (_graph.ActiveState != _poseState)
        {
            _poseState           = _graph.ActiveState;
            _stateElapsedSeconds = 0.0;
            return;
        }

        _stateElapsedSeconds += dt;
    }

    private MaotaiPoseFrame BuildPose(
        in MaotaiMotionInput input,
        double dt)
    {
        var speedRatio = Math.Clamp(
            Math.Abs(_locomotion.VelocityX) / WalkRunSpeedReference,
            0.0,
            1.0);
        var gaitPhase       = _locomotion.GaitPhase;
        var gaitAngle       = gaitPhase * Math.PI * 2.0;
        var grounded        = _locomotion.IsGrounded;
        var facingSign      = _locomotion.FacingSign;
        var blend           = SmoothStep(_graph.TransitionProgress);
        var yawnProgress    = GetYawnProgress();
        if (_graph.ActiveState == MaotaiMotionState.Yawn)
        {
            // Dynamic handoff source : retain the exact rendered yawn phase so an external state change
            // can leave the in-flight envelope from the pose the user actually saw on the previous frame.
            _lastYawnProgress = yawnProgress;
        }
        else if (_graph.ActiveState == MaotaiMotionState.WorkSettle)
        {
            // Re-entrant work exit : retain the exact partial settle pose rendered on the previous frame.
            _lastWorkSettleBlend = blend;
        }
        else if (_graph.ActiveState == MaotaiMotionState.WorkTired)
        {
            // Re-entrant mood exit : retain the actual partial tired pose so Recover can leave from
            // the fatigue amount the user saw instead of jumping to the full tired endpoint.
            _lastTiredBlend = blend;
        }
        else if (_graph.ActiveState == MaotaiMotionState.WorkAnnoyed)
        {
            // Re-entrant mood exit : retain the actual partial annoyed pose. A real state change may
            // interrupt the attack before its endpoint, so Recover must start from what was rendered.
            _lastAnnoyedBlend = blend;
        }

        var mouthOpenAmount = _graph.ActiveState == MaotaiMotionState.Yawn
            ? Math.Sin(yawnProgress * Math.PI)
            : 0.0;

        var bodyBob = grounded && speedRatio > 0.02
            ? Math.Sin(gaitAngle * 2.0) * (0.55 + (speedRatio * 1.45))
            : 0.0;
        var breathing   = Math.Sin((_elapsedSeconds * 2.1) + _idlePhaseOffset) * 0.32;
        var bodyWorldY  = -44.0 + _locomotion.VerticalOffset + bodyBob + breathing;
        var bodyTilt    = -facingSign * speedRatio * 5.4;
        var bodyScaleX  = 1.0;
        var bodyScaleY  = 1.0;
        var headOffsetY = 0.0;
        var headBiasDeg = 0.0;
        var earDrop     = 0.0;
        var earTension  = 0.0;

        ApplyActionPose(
            ref bodyWorldY,
            ref bodyTilt,
            ref bodyScaleX,
            ref bodyScaleY,
            ref headOffsetY,
            ref headBiasDeg,
            ref earDrop,
            ref earTension,
            blend,
            facingSign);

        // Sleep hover          : ordinary pointer presence must not steer the sleeping head; real interactions still wake through the graph.
        var tracksPointer = input.PointerInside &&
            _graph.ActiveState != MaotaiMotionState.Sleep;
        var pointerX = tracksPointer
            ? Math.Clamp(input.PointerX, -1.0, 1.0)
            : 0.0;
        var pointerY = tracksPointer
            ? Math.Clamp(input.PointerY, -1.0, 1.0)
            : 0.0;
        var idleLook = tracksPointer
            ? 0.0
            : Math.Sin((_elapsedSeconds * 0.82) + _idlePhaseOffset) * 1.15;

        _headX.Step((pointerX * 2.0) + (idleLook * 0.18), dt);
        _headY.Step((pointerY * 1.25) + headOffsetY, dt);
        _headRotate.Step(
            (pointerX * 7.0) + idleLook - (bodyTilt * 0.22) + headBiasDeg,
            dt);

        var earGait = Math.Sin(gaitAngle + 0.45) * (0.8 + (speedRatio * 2.3));
        _leftEar.Step((_headRotate.Value * 0.32) + earGait - earTension, dt);
        _rightEar.Step((_headRotate.Value * 0.28) - (earGait * 0.82) + earTension, dt);

        var tailEnergy = input.BaseState switch
        {
            MaotaiBaseState.Offline => 0.12,
            MaotaiBaseState.Error   => 0.18,
            MaotaiBaseState.Working => 0.52,
            _                       => 0.68,
        };
        var tailTarget = Math.Sin((gaitAngle * 1.2) + (_elapsedSeconds * 1.35)) *
            (4.0 + (tailEnergy * 10.0));
        if (_graph.ActiveState == MaotaiMotionState.Sleep)
        {
            // Sleep tail          : keep a faint living sway without carrying awake Resting wag energy into sleep.
            tailTarget *= 0.22;
        }
        else if (_graph.ActiveState == MaotaiMotionState.WorkTired ||
                 _graph.ActiveState == MaotaiMotionState.Yawn)
        {
            tailTarget *= 0.42;
        }
        else if (_graph.ActiveState == MaotaiMotionState.WorkAnnoyed)
        {
            tailTarget *= 1.35;
        }

        _tailBase.Step(tailTarget, dt);
        _tailMid.Step((_tailBase.Value * 1.08) - (_locomotion.VelocityX * 0.025), dt);
        _tailTip.Step((_tailMid.Value * 1.12) - (_locomotion.VelocityX * 0.018), dt);

        // Canonical front view : left/right asset pairs straddle body center; gait phase still carries depth.
        var frontLeft = BuildLockedLeg(
            ref _frontLeftLock,
            gaitPhase,
            speedRatio,
            bodyWorldY,
            facingSign,
            grounded,
            shoulderLocalX: -17.5,
            shoulderLocalY: 9.5,
            frontLeg: true);
        var frontRight = BuildLockedLeg(
            ref _frontRightLock,
            Wrap01(gaitPhase + 0.50),
            speedRatio,
            bodyWorldY,
            facingSign,
            grounded,
            shoulderLocalX: 15.5,
            shoulderLocalY: 10.0,
            frontLeg: true);
        var hindLeft = BuildLockedLeg(
            ref _hindLeftLock,
            Wrap01(gaitPhase + 0.50),
            speedRatio,
            bodyWorldY,
            facingSign,
            grounded,
            shoulderLocalX: -15.0,
            shoulderLocalY: 12.0,
            frontLeg: false);
        var hindRight = BuildLockedLeg(
            ref _hindRightLock,
            gaitPhase,
            speedRatio,
            bodyWorldY,
            facingSign,
            grounded,
            shoulderLocalX: 17.0,
            shoulderLocalY: 12.0,
            frontLeg: false);

        var workPawExitTransition =
            _graph.ActiveState == MaotaiMotionState.Idle &&
            _graph.IsTransitioning &&
            IsWorkingPawState(_graph.PreviousState);
        if (IsWorkingPawState(_graph.ActiveState) || workPawExitTransition)
        {
            var workPawState = workPawExitTransition
                ? _graph.PreviousState
                : _graph.ActiveState;
            var workPawBlend = workPawExitTransition
                ? 1.0
                : blend;
            var cadenceHz = GetTypingCadenceHz(workPawState, workPawBlend);
            var amplitude = GetTypingAmplitude(workPawState, workPawBlend);
            if (_graph.ActiveState == MaotaiMotionState.Yawn)
            {
                cadenceHz = Lerp(1.55, 0.40, mouthOpenAmount);
                amplitude = Lerp(1.15, 0.55, mouthOpenAmount);
            }
            else if (_graph.ActiveState == MaotaiMotionState.WorkTyping &&
                     _graph.PreviousState == MaotaiMotionState.Yawn &&
                     _graph.IsTransitioning)
            {
                cadenceHz = Lerp(1.55, 3.10, blend);
                amplitude = Lerp(1.15, 1.65, blend);
            }

            _typingPhaseRadians = WrapRadians(
                _typingPhaseRadians + (dt * Math.PI * 2.0 * cadenceHz));

            var leftPress  = (1.0 - Math.Cos(_typingPhaseRadians)) * amplitude;
            var rightPress = (1.0 - Math.Cos(_typingPhaseRadians + Math.PI)) * amplitude;

            var workLeft = BuildWorkPaw(
                shoulderLocalX: -17.5,
                shoulderLocalY: 9.5,
                keyboardLocalX: -12.0,
                keyboardLocalY: 39.0,
                pressOffset: leftPress,
                bodyWorldY,
                facingSign);
            var workRight = BuildWorkPaw(
                shoulderLocalX: 15.5,
                shoulderLocalY: 10.0,
                keyboardLocalX: 12.0,
                keyboardLocalY: 39.5,
                pressOffset: rightPress,
                bodyWorldY,
                facingSign);

            // Work handoff        : WorkSettle ends with the current standing IK. WorkTyping then lowers both paws onto
            // the keyboard over the graph's existing transition instead of teleporting targets on its first frame.
            if (_graph.ActiveState == MaotaiMotionState.WorkTyping &&
                _graph.PreviousState == MaotaiMotionState.WorkSettle &&
                _graph.IsTransitioning)
            {
                frontLeft  = BlendLegPose(frontLeft, workLeft, blend);
                frontRight = BlendLegPose(frontRight, workRight, blend);
            }
            else if (workPawExitTransition)
            {
                // Work exit handoff : keep the last keyboard IK as the source, then release both paws
                // toward standing IK over the graph transition instead of snapping on the first Idle frame.
                frontLeft  = BlendLegPose(workLeft, frontLeft, blend);
                frontRight = BlendLegPose(workRight, frontRight, blend);
            }
            else
            {
                frontLeft  = workLeft;
                frontRight = workRight;
            }
        }

        var baseEyeState = input.BaseState switch
        {
            MaotaiBaseState.Offline => MaotaiEyeState.Closed,
            MaotaiBaseState.Error   => MaotaiEyeState.Half,
            _ => _graph.ActiveState switch
            {
                MaotaiMotionState.Sleep       => MaotaiEyeState.Closed,
                MaotaiMotionState.Wake        => MaotaiEyeState.Half,
                MaotaiMotionState.WorkTired   => MaotaiEyeState.Half,
                MaotaiMotionState.Yawn        => MaotaiEyeState.Closed,
                MaotaiMotionState.WorkAnnoyed => MaotaiEyeState.Half,
                MaotaiMotionState.Recover     => MaotaiEyeState.Open,
                _                             => MaotaiEyeState.Open,
            },
        };
        var eyeState = MaotaiNaturalBlink.Resolve(
            baseEyeState,
            _elapsedSeconds,
            _idlePhaseOffset);
        var mouthState = input.BaseState switch
        {
            MaotaiBaseState.Error   => MaotaiMouthState.Annoyed,
            MaotaiBaseState.Offline => MaotaiMouthState.Tired,
            _ => input.Interaction switch
            {
                MaotaiInteractionKind.Pat       => MaotaiMouthState.Tongue,
                MaotaiInteractionKind.Paw       => MaotaiMouthState.Tongue,
                MaotaiInteractionKind.Celebrate => MaotaiMouthState.Tongue,
                _ => _graph.ActiveState switch
                {
                    MaotaiMotionState.Sleep       => MaotaiMouthState.Tired,
                    MaotaiMotionState.WorkTired   => MaotaiMouthState.Tired,
                    MaotaiMotionState.Yawn        => MaotaiMouthState.Yawn,
                    MaotaiMotionState.WorkAnnoyed => MaotaiMouthState.Annoyed,
                    MaotaiMotionState.Recover     => MaotaiMouthState.Smile,
                    _                             => MaotaiMouthState.Smile,
                },
            },
        };

        var gaze = MaotaiAutonomousGaze.Resolve(
            input.PointerInside,
            input.PointerX,
            input.PointerY,
            allowAutonomous: input.BaseState == MaotaiBaseState.Resting,
            _elapsedSeconds,
            _idlePhaseOffset);
        var pupilX = gaze.X;
        var pupilY = gaze.Y;

        return new MaotaiPoseFrame
        {
            Root                    = new MaotaiBonePose(_locomotion.PositionX, 0.0, 0.0),
            Body                    = new MaotaiBonePose(0.0, bodyWorldY, bodyTilt, bodyScaleX, bodyScaleY),
            Chest                   = new MaotaiBonePose(facingSign * 2.0, -4.0, bodyTilt * 0.22),
            Head                    = new MaotaiBonePose(_headX.Value, -29.0 + _headY.Value, _headRotate.Value),
            LeftEar                 = new MaotaiBonePose(-11.0, -20.0 + earDrop, _leftEar.Value),
            RightEar                = new MaotaiBonePose(11.0, -20.0 + earDrop, _rightEar.Value),
            LeftPupil               = new MaotaiBonePose(-6.0 + pupilX, -2.0 + pupilY, 0.0),
            RightPupil              = new MaotaiBonePose(6.0 + pupilX, -2.0 + pupilY, 0.0),
            FrontLeftUpper          = frontLeft.Upper,
            FrontLeftLower          = frontLeft.Lower,
            FrontLeftPaw            = frontLeft.Paw,
            FrontRightUpper         = frontRight.Upper,
            FrontRightLower         = frontRight.Lower,
            FrontRightPaw           = frontRight.Paw,
            HindLeftUpper           = hindLeft.Upper,
            HindLeftLower           = hindLeft.Lower,
            HindLeftPaw             = hindLeft.Paw,
            HindRightUpper          = hindRight.Upper,
            HindRightLower          = hindRight.Lower,
            HindRightPaw            = hindRight.Paw,
            TailBase                = new MaotaiBonePose(-20.0 * facingSign, -10.0, _tailBase.Value),
            TailMid                 = new MaotaiBonePose(-11.0 * facingSign, -8.0, _tailMid.Value),
            TailTip                 = new MaotaiBonePose(-10.0 * facingSign, -7.0, _tailTip.Value),
            EyeState                = eyeState,
            MouthState              = mouthState,
            MotionState             = _graph.ActiveState,
            PreviousMotionState     = _graph.PreviousState,
            MotionTransitionBlend   = blend,
            YawnProgress            = yawnProgress,
            MouthOpenAmount         = mouthOpenAmount,
            FacingSign              = facingSign,
            FrontLeftSupport        = frontLeft.IsSupport,
            FrontLeftPawWorldX      = frontLeft.PawWorldX,
            FrontLeftPawWorldY      = frontLeft.PawWorldY,
            FrontRightSupport       = frontRight.IsSupport,
            FrontRightPawWorldX     = frontRight.PawWorldX,
            FrontRightPawWorldY     = frontRight.PawWorldY,
            HindLeftSupport         = hindLeft.IsSupport,
            HindLeftPawWorldX       = hindLeft.PawWorldX,
            HindLeftPawWorldY       = hindLeft.PawWorldY,
            HindRightSupport        = hindRight.IsSupport,
            HindRightPawWorldX      = hindRight.PawWorldX,
            HindRightPawWorldY      = hindRight.PawWorldY,
            StageX                  = _locomotion.PositionX,
            StageYOffset            = _locomotion.VerticalOffset,
        };
    }

    private void ApplyActionPose(
        ref double bodyWorldY,
        ref double bodyTilt,
        ref double bodyScaleX,
        ref double bodyScaleY,
        ref double headOffsetY,
        ref double headBiasDeg,
        ref double earDrop,
        ref double earTension,
        double blend,
        int facingSign)
    {
        switch (_graph.ActiveState)
        {
            case MaotaiMotionState.Idle:
                if (_graph.IsTransitioning &&
                    (_graph.PreviousState == MaotaiMotionState.WorkTyping ||
                     _graph.PreviousState == MaotaiMotionState.WorkSettle))
                {
                    // Work exit body : leave from the exact body posture rendered on the previous work frame.
                    var residual = 1.0 - blend;
                    var sourceBlend = _graph.PreviousState == MaotaiMotionState.WorkSettle
                        ? Math.Clamp(_lastWorkSettleBlend, 0.0, 1.0)
                        : 1.0;
                    bodyWorldY += 2.0 * sourceBlend * residual;
                    bodyScaleY -= 0.015 * sourceBlend * residual;
                }
                break;

            case MaotaiMotionState.JumpPrep:
                bodyWorldY += 3.2 * blend;
                bodyScaleX += 0.055 * blend;
                bodyScaleY -= 0.085 * blend;
                headOffsetY += 1.0 * blend;
                break;

            case MaotaiMotionState.JumpAir:
                // Jump boundary       : keep the completed prep squash on the first airborne frame, then extend over the graph hop.
                bodyWorldY += Lerp(3.2, 0.0, blend);
                bodyScaleX += Lerp(0.055, -0.018, blend);
                bodyScaleY += Lerp(-0.085, 0.025, blend);
                headOffsetY += Lerp(1.0, -0.7, blend);
                earDrop     += 1.0 * blend;
                break;

            case MaotaiMotionState.Land:
            {
                const double impactAttackSeconds = 0.05;
                var attack = SmoothStep(Math.Clamp(
                    _stateElapsedSeconds / impactAttackSeconds,
                    0.0,
                    1.0));
                var recoil = Math.Exp(-Math.Max(0.0, _stateElapsedSeconds - impactAttackSeconds) * 9.0);
                var compression = attack * recoil;
                var airResidual = 1.0 - attack;

                // Landing boundary    : first contact keeps the airborne stretch exactly; compression then builds over 50 ms before recoil.
                bodyWorldY += 2.8 * compression;
                bodyScaleX += (-0.018 * airResidual) + (0.060 * compression);
                bodyScaleY += (0.025 * airResidual) - (0.075 * compression);
                headOffsetY += (-0.7 * airResidual) + (1.4 * compression);
                earDrop     += (1.0 * airResidual) + (1.2 * compression);
                break;
            }

            case MaotaiMotionState.Sit:
                bodyWorldY += 7.0 * blend;
                bodyScaleY -= 0.055 * blend;
                headOffsetY -= 1.0 * blend;
                break;

            case MaotaiMotionState.LieDown:
                // State boundary      : inherit the exact Sit endpoint before easing toward the lie-down endpoint.
                bodyWorldY += Lerp(7.0, 10.0, blend);
                bodyScaleX += Lerp(0.0, 0.050, blend);
                bodyScaleY -= Lerp(0.055, 0.095, blend);
                headOffsetY += Lerp(-1.0, 4.0, blend);
                break;

            case MaotaiMotionState.Sleep:
                // State boundary      : Sleep is a continuation of LieDown, not a fresh neutral-origin pose.
                bodyWorldY += Lerp(10.0, 11.5, blend);
                bodyScaleX += Lerp(0.050, 0.055, blend);
                bodyScaleY -= Lerp(0.095, 0.100, blend);
                headOffsetY += Lerp(4.0, 6.0, blend);
                headBiasDeg += 7.5 * facingSign * blend;
                earDrop     += 4.0 * blend;
                break;

            case MaotaiMotionState.Wake:
                bodyWorldY += Lerp(11.5, 5.4, blend);
                bodyScaleX += 0.055 * (1.0 - blend);
                bodyScaleY -= 0.100 * (1.0 - blend);
                headOffsetY += 4.5 * (1.0 - blend);
                earDrop     += 4.0 * (1.0 - blend);
                break;

            case MaotaiMotionState.GetUp:
                bodyWorldY += 5.4 * (1.0 - blend);
                break;

            case MaotaiMotionState.WorkSettle:
                bodyWorldY += 2.0 * blend;
                bodyScaleY -= 0.015 * blend;
                break;

            case MaotaiMotionState.WorkTyping:
                if (_graph.PreviousState == MaotaiMotionState.WorkSettle &&
                    _graph.IsTransitioning)
                {
                    // Work handoff     : preserve WorkSettle's completed body posture while paws move to the keyboard.
                    bodyWorldY += 2.0;
                    bodyScaleY -= 0.015;
                }
                else
                {
                    bodyWorldY += 2.0 * blend;
                    bodyScaleY -= 0.015 * blend;
                }
                break;

            case MaotaiMotionState.WorkTired:
                // Work-cycle boundary : inherit the stable typing body before easing into the tired endpoint.
                bodyWorldY += Lerp(2.0, 2.6, blend);
                bodyScaleX += 0.018 * blend;
                bodyScaleY -= Lerp(0.015, 0.045, blend);
                headOffsetY += 4.2 * blend;
                headBiasDeg += 3.0 * facingSign * blend;
                earDrop     += 3.2 * blend;
                earTension   = 2.0 * blend;
                break;

            case MaotaiMotionState.Yawn:
            {
                var phase         = GetYawnProgress();
                var envelope      = Math.Sin(phase * Math.PI);
                var tiredResidual = (1.0 - phase) * (1.0 - phase);
                bodyWorldY += (2.6 * tiredResidual) - (1.6 * envelope);
                bodyScaleX += (0.018 * tiredResidual) - (0.025 * envelope);
                bodyScaleY += (-0.045 * tiredResidual) + (0.070 * envelope);
                headOffsetY += (4.2 * tiredResidual) - (2.4 * envelope);
                headBiasDeg += (3.0 * facingSign * tiredResidual) -
                    (4.0 * facingSign * envelope);
                earDrop += (3.2 * tiredResidual) + (1.4 * envelope);
                earTension = 2.0 * tiredResidual;
                break;
            }

            case MaotaiMotionState.WorkAnnoyed:
                // Work-cycle boundary : inherit the stable typing body before easing into the annoyed endpoint.
                bodyWorldY += Lerp(2.0, 1.0, blend);
                bodyScaleX -= 0.020 * blend;
                bodyScaleY += Lerp(-0.015, 0.022, blend);
                bodyTilt   -= 3.8 * facingSign * blend;
                headOffsetY -= 0.8 * blend;
                headBiasDeg -= 2.8 * facingSign * blend;
                earDrop     -= 0.8 * blend;
                earTension   = 4.5 * blend;
                break;

            case MaotaiMotionState.Recover:
            {
                var residual = 1.0 - blend;
                if (_graph.PreviousState == MaotaiMotionState.WorkTired)
                {
                    // Interrupted tired exit : reconstruct the actual partial tired source. Stable tired
                    // caches 1.0, preserving the existing full-endpoint recovery exactly.
                    var sourceBlend = Math.Clamp(_lastTiredBlend, 0.0, 1.0);
                    bodyWorldY += Lerp(2.0, 2.6, sourceBlend) * residual;
                    bodyScaleX += 0.018 * sourceBlend * residual;
                    bodyScaleY -= Lerp(0.015, 0.045, sourceBlend) * residual;
                    headOffsetY += 4.2 * sourceBlend * residual;
                    headBiasDeg += 3.0 * facingSign * sourceBlend * residual;
                    earDrop += 3.2 * sourceBlend * residual;
                    earTension = 2.0 * sourceBlend * residual;
                }
                else if (_graph.PreviousState == MaotaiMotionState.Yawn)
                {
                    // Interrupted yawn exit : Yawn is a time-varying envelope, so preserve the exact
                    // phase rendered on the previous frame rather than substituting any fixed endpoint.
                    var phase = Math.Clamp(_lastYawnProgress, 0.0, 1.0);
                    var envelope = Math.Sin(phase * Math.PI);
                    var tiredResidual = (1.0 - phase) * (1.0 - phase);
                    bodyWorldY += ((2.6 * tiredResidual) - (1.6 * envelope)) * residual;
                    bodyScaleX += ((0.018 * tiredResidual) - (0.025 * envelope)) * residual;
                    bodyScaleY += ((-0.045 * tiredResidual) + (0.070 * envelope)) * residual;
                    headOffsetY += ((4.2 * tiredResidual) - (2.4 * envelope)) * residual;
                    headBiasDeg += ((3.0 * facingSign * tiredResidual) -
                        (4.0 * facingSign * envelope)) * residual;
                    earDrop += ((3.2 * tiredResidual) + (1.4 * envelope)) * residual;
                    earTension = 2.0 * tiredResidual * residual;
                }
                else if (_graph.PreviousState == MaotaiMotionState.WorkAnnoyed)
                {
                    // Interrupted annoyance exit : preserve the exact partial attack that was rendered.
                    // A stable annoyance caches 1.0, so the ordinary work-cycle recovery is unchanged.
                    var sourceBlend = Math.Clamp(_lastAnnoyedBlend, 0.0, 1.0);
                    bodyWorldY += Lerp(2.0, 1.0, sourceBlend) * residual;
                    bodyTilt -= 3.8 * facingSign * sourceBlend * residual;
                    bodyScaleX -= 0.020 * sourceBlend * residual;
                    bodyScaleY += Lerp(-0.015, 0.022, sourceBlend) * residual;
                    headOffsetY -= 0.8 * sourceBlend * residual;
                    headBiasDeg -= 2.8 * facingSign * sourceBlend * residual;
                    earDrop -= 0.8 * sourceBlend * residual;
                    earTension = 4.5 * sourceBlend * residual;
                }
                else
                {
                    bodyWorldY  += 1.0 * residual;
                    bodyTilt    -= 3.8 * facingSign * residual;
                    bodyScaleX  -= 0.020 * residual;
                    bodyScaleY  += 0.022 * residual;
                    headOffsetY -= 0.8 * residual;
                    headBiasDeg -= 2.8 * facingSign * residual;
                    earDrop     -= 0.8 * residual;
                    earTension   = 4.5 * residual;
                }
                break;
            }
        }
    }

    private double GetYawnProgress() =>
        _graph.ActiveState == MaotaiMotionState.Yawn
            ? Math.Clamp(_stateElapsedSeconds / YawnEnvelopeSeconds, 0.0, 1.0)
            : 0.0;

    /// <summary>把地面站姿连续混入坐下/趴下/睡眠收腿，避免身体下沉时脚掌仍锁在世界地面。</summary>
    private double GetRestLegTuck()
    {
        var blend = SmoothStep(_graph.TransitionProgress);
        return _graph.ActiveState switch
        {
            MaotaiMotionState.Sit     => 0.28 * blend,
            MaotaiMotionState.LieDown => Lerp(0.28, 1.0, blend),
            MaotaiMotionState.Sleep   => 1.0,
            MaotaiMotionState.Wake    => Lerp(1.0, 0.55, blend),
            MaotaiMotionState.GetUp   => 0.55 * (1.0 - blend),
            _                         => 0.0,
        };
    }

    private MaotaiLegPose BuildWorkPaw(
        double shoulderLocalX,
        double shoulderLocalY,
        double keyboardLocalX,
        double keyboardLocalY,
        double pressOffset,
        double bodyWorldY,
        int facingSign)
    {
        shoulderLocalX *= facingSign;
        keyboardLocalX *= facingSign;

        var pawWorldX = _locomotion.PositionX + keyboardLocalX;
        var pawWorldY = bodyWorldY + keyboardLocalY + pressOffset;

        return SolveLeg(
            shoulderLocalX,
            shoulderLocalY,
            pawWorldX,
            pawWorldY,
            bodyWorldY,
            facingSign,
            frontLeg: true,
            isSupport: false);
    }

    private MaotaiLegPose BuildLockedLeg(
        ref MaotaiFootLockState lockState,
        double phase,
        double speedRatio,
        double bodyWorldY,
        int facingSign,
        bool grounded,
        double shoulderLocalX,
        double shoulderLocalY,
        bool frontLeg)
    {
        shoulderLocalX *= facingSign;
        var moving  = Math.Abs(_locomotion.VelocityX) > 2.0;
        var support = grounded && moving && phase < SupportPhase;
        var stride  = (frontLeg ? 12.0 : 10.0) +
            (speedRatio * (frontLeg ? 13.0 : 11.0));

        double pawWorldX;
        double pawWorldY;

        if (support)
        {
            if (!lockState.WasSupport)
            {
                lockState.AnchorWorldX = _locomotion.PositionX +
                    shoulderLocalX +
                    (facingSign * stride * 0.34);
                lockState.AnchorWorldY = GroundWorldY;
            }

            pawWorldX = lockState.AnchorWorldX;
            pawWorldY = lockState.AnchorWorldY;
        }
        else if (!grounded)
        {
            pawWorldX = _locomotion.PositionX + shoulderLocalX + (facingSign * (frontLeg ? 5.0 : -3.0));
            pawWorldY = bodyWorldY + (frontLeg ? 33.0 : 35.0);
        }
        else if (!moving)
        {
            var restTuck = GetRestLegTuck();
            var standingPawLocalX = shoulderLocalX + (facingSign * (frontLeg ? 3.0 : -2.0));
            var tuckedPawLocalX   = shoulderLocalX * 0.72;
            var tuckedPawWorldY   = bodyWorldY + (frontLeg ? 26.0 : 27.0);

            // Resting foot       : interpolate in world space so Sit → LieDown → Sleep never snaps off the floor.
            pawWorldX = Lerp(
                _locomotion.PositionX + standingPawLocalX,
                _locomotion.PositionX + tuckedPawLocalX,
                restTuck);
            pawWorldY = Lerp(GroundWorldY, tuckedPawWorldY, restTuck);
        }
        else
        {
            var swingPhase = phase < SupportPhase
                ? 0.0
                : (phase - SupportPhase) / (1.0 - SupportPhase);
            var swingAngle = swingPhase * Math.PI;
            pawWorldX = _locomotion.PositionX +
                shoulderLocalX +
                (facingSign * ((swingPhase * 2.0) - 1.0) * stride * 0.58);
            pawWorldY = GroundWorldY -
                (Math.Sin(swingAngle) * (4.5 + (speedRatio * (frontLeg ? 6.5 : 5.5))));
        }

        if (grounded && moving && !support)
        {
            // Swing-only lane    : planted paws keep their exact world anchor; only airborne paws receive cosmetic lateral limits.
            // Seam prevention    : this preserves foot-lock while keeping the visible swing silhouette away from center-crossing X shapes.
            var laneRadius = frontLeg ? 4.5 : 4.0;
            var pawLocalX  = pawWorldX - _locomotion.PositionX;
            pawLocalX = Math.Clamp(
                pawLocalX,
                shoulderLocalX - laneRadius,
                shoulderLocalX + laneRadius);
            pawWorldX = _locomotion.PositionX + pawLocalX;
        }

        lockState.WasSupport = support;
        var solved = SolveLeg(
            shoulderLocalX,
            shoulderLocalY,
            pawWorldX,
            pawWorldY,
            bodyWorldY,
            facingSign,
            frontLeg,
            support);

        var standingRelax = grounded
            ? 1.0 - SmoothStep(speedRatio / StandingRelaxSpeedRatio)
            : 0.0;
        return RelaxLegTowardStanding(solved, standingRelax);
    }

    private MaotaiLegPose SolveLeg(
        double shoulderLocalX,
        double shoulderLocalY,
        double pawWorldX,
        double pawWorldY,
        double bodyWorldY,
        int facingSign,
        bool frontLeg,
        bool isSupport)
    {
        var pawLocalX   = pawWorldX - _locomotion.PositionX;
        var pawLocalY   = pawWorldY - bodyWorldY;
        var upperLength = frontLeg ? FrontLegUpperLength : HindLegUpperLength;
        var lowerLength = frontLeg ? FrontLegLowerLength : HindLegLowerLength;
        var bendSign    = frontLeg ? -facingSign : facingSign;
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
            pawWorldY,
            isSupport);
    }

    private static MaotaiLegPose RelaxLegTowardStanding(
        in MaotaiLegPose leg,
        double amount)
    {
        var t = Math.Clamp(amount, 0.0, 1.0);
        if (t <= 0.0)
        {
            return leg;
        }

        var shoulderX = leg.Upper.X;
        var shoulderY = leg.Upper.Y;
        var pawX      = leg.Paw.X;
        var pawY      = leg.Paw.Y;
        var straightJointX = Lerp(shoulderX, pawX, 0.515);
        var straightJointY = Lerp(shoulderY, pawY, 0.515);
        var jointX = Lerp(leg.Lower.X, straightJointX, t);
        var jointY = Lerp(leg.Lower.Y, straightJointY, t);
        var upperAngle = Math.Atan2(jointY - shoulderY, jointX - shoulderX) * (180.0 / Math.PI);
        var lowerAngle = Math.Atan2(pawY - jointY, pawX - jointX) * (180.0 / Math.PI);

        return leg with
        {
            Upper = leg.Upper with { RotationDeg = upperAngle },
            Lower = leg.Lower with { X = jointX, Y = jointY, RotationDeg = lowerAngle },
            Paw   = leg.Paw with { RotationDeg = -lowerAngle * 0.08 },
        };
    }

    private static MaotaiLegPose BlendLegPose(
        in MaotaiLegPose from,
        in MaotaiLegPose to,
        double amount)
    {
        var t = Math.Clamp(amount, 0.0, 1.0);
        return new MaotaiLegPose(
            BlendBonePose(from.Upper, to.Upper, t),
            BlendBonePose(from.Lower, to.Lower, t),
            BlendBonePose(from.Paw, to.Paw, t),
            Lerp(from.PawWorldX, to.PawWorldX, t),
            Lerp(from.PawWorldY, to.PawWorldY, t),
            t < 0.5 ? from.IsSupport : to.IsSupport);
    }

    private static MaotaiBonePose BlendBonePose(
        in MaotaiBonePose from,
        in MaotaiBonePose to,
        double amount) =>
        new(
            Lerp(from.X, to.X, amount),
            Lerp(from.Y, to.Y, amount),
            LerpAngleDegrees(from.RotationDeg, to.RotationDeg, amount),
            Lerp(from.ScaleX, to.ScaleX, amount),
            Lerp(from.ScaleY, to.ScaleY, amount));

    private static double LerpAngleDegrees(
        double from,
        double to,
        double amount)
    {
        var delta = ((to - from + 540.0) % 360.0) - 180.0;
        return from + (delta * Math.Clamp(amount, 0.0, 1.0));
    }

    private static bool IsWorkingPawState(MaotaiMotionState state) =>
        state is MaotaiMotionState.WorkTyping or
            MaotaiMotionState.WorkTired or
            MaotaiMotionState.Yawn or
            MaotaiMotionState.WorkAnnoyed or
            MaotaiMotionState.Recover;

    private static double GetTypingCadenceHz(MaotaiMotionState state, double blend) =>
        state switch
        {
            MaotaiMotionState.WorkTired   => Lerp(3.1, 1.55, blend),
            MaotaiMotionState.WorkAnnoyed => Lerp(3.1, 4.40, blend),
            MaotaiMotionState.Recover     => Lerp(4.40, 3.1, blend),
            _                             => 3.1,
        };

    private static double GetTypingAmplitude(MaotaiMotionState state, double blend) =>
        state switch
        {
            MaotaiMotionState.WorkTired   => Lerp(1.65, 1.15, blend),
            MaotaiMotionState.WorkAnnoyed => Lerp(1.65, 2.25, blend),
            MaotaiMotionState.Recover     => Lerp(2.25, 1.65, blend),
            _                             => 1.65,
        };

    private static double SmoothStep(double value)
    {
        var t = Math.Clamp(value, 0.0, 1.0);
        return t * t * (3.0 - (2.0 * t));
    }

    private static double Lerp(double from, double to, double t) =>
        from + ((to - from) * Math.Clamp(t, 0.0, 1.0));

    private static double WrapRadians(double value)
    {
        var period = Math.PI * 2.0;
        value %= period;
        return value < 0.0
            ? value + period
            : value;
    }

    private static double Wrap01(double value)
    {
        value %= 1.0;
        return value < 0.0
            ? value + 1.0
            : value;
    }
}
