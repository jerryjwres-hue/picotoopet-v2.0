namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>连续位置、速度、步态相位和跳跃高度控制；不直接操作任何 WPF 元素。</summary>
internal sealed class MaotaiLocomotionController
{
    private const double WalkSpeed             = 38.0;
    private const double RunSpeed              = 76.0;
    private const double WalkAcceleration      = 150.0;
    private const double RunAcceleration       = 230.0;
    private const double Deceleration          = 260.0;
    private const double StopDistance          = 1.25;
    private const double GaitCyclesPerUnit     = 0.018;
    private const double JumpVelocity          = -146.0;
    private const double Gravity               = 430.0;
    private const double FacingFlipSpeed       = 5.0;
    private const double TurnAnticipationRate  = 5.5;

    public MaotaiLocomotionController(double initialPositionX)
    {
        PositionX = double.IsFinite(initialPositionX)
            ? initialPositionX
            : 0.0;
    }

    public double PositionX { get; private set; }

    public double VelocityX { get; private set; }

    public double GaitPhase { get; private set; }

    /// <summary>0=walk/idle，1=full run；由真实速度连续计算，不由离散状态硬切。</summary>
    public double RunBlend => Math.Clamp(
        (Math.Abs(VelocityX) - (WalkSpeed * 0.70)) /
        Math.Max(1.0, RunSpeed - (WalkSpeed * 0.70)),
        0.0,
        1.0);

    /// <summary>-1..1 的转向预备方向；反向请求时先积累身体张力，再在低速区翻身。</summary>
    public double TurnAnticipation { get; private set; }

    public double VerticalOffset { get; private set; }

    public double VerticalVelocity { get; private set; }

    public bool IsGrounded { get; private set; } = true;

    public bool LandedThisFrame { get; private set; }

    public int FacingSign { get; private set; } = 1;

    /// <summary>以连续速度/加速度推进位置；长帧被裁剪，舞台边界始终为硬约束。</summary>
    public void Update(
        double deltaTime,
        double targetX,
        bool wantsRun,
        bool wantsJump,
        double minX,
        double maxX)
    {
        LandedThisFrame = false;
        if (!double.IsFinite(deltaTime) ||
            !double.IsFinite(targetX) ||
            !double.IsFinite(minX) ||
            !double.IsFinite(maxX))
        {
            return;
        }

        if (minX > maxX)
        {
            (minX, maxX) = (maxX, minX);
        }

        var dt = Math.Clamp(deltaTime, 0.0, 0.05);
        if (dt <= 0)
        {
            PositionX = Math.Clamp(PositionX, minX, maxX);
            return;
        }

        targetX = Math.Clamp(targetX, minX, maxX);
        var distance       = targetX - PositionX;
        var direction      = Math.Sign(distance);
        var velocitySign   = Math.Sign(VelocityX);
        var reversing      = direction != 0 && velocitySign != 0 && direction != velocitySign;
        var turnTarget     = reversing ? direction : 0.0;

        // Turn anticipation : do not mirror the complete raster skeleton while momentum still travels the old way.
        TurnAnticipation = MoveTowards(
            TurnAnticipation,
            turnTarget,
            TurnAnticipationRate * dt);

        if (direction != 0 &&
            (Math.Abs(VelocityX) <= FacingFlipSpeed || velocitySign == direction))
        {
            FacingSign = direction;
        }

        var desiredSpeed = Math.Abs(distance) <= StopDistance
            ? 0.0
            : direction * (wantsRun ? RunSpeed : WalkSpeed);
        var acceleration = Math.Abs(desiredSpeed) < Math.Abs(VelocityX) || reversing
            ? Deceleration
            : wantsRun ? RunAcceleration : WalkAcceleration;

        VelocityX = MoveTowards(VelocityX, desiredSpeed, acceleration * dt);
        var nextX = PositionX + (VelocityX * dt);

        if ((distance > 0 && nextX > targetX) ||
            (distance < 0 && nextX < targetX))
        {
            nextX     = targetX;
            VelocityX = 0.0;
        }

        PositionX = Math.Clamp(nextX, minX, maxX);
        if ((PositionX <= minX && VelocityX < 0) ||
            (PositionX >= maxX && VelocityX > 0))
        {
            VelocityX = 0.0;
        }

        // Gait phase        : distance-driven phase naturally preserves foot cadence through walk/run blending.
        GaitPhase = Wrap01(
            GaitPhase + (Math.Abs(VelocityX) * GaitCyclesPerUnit * dt));

        if (wantsJump && IsGrounded)
        {
            IsGrounded       = false;
            VerticalVelocity = JumpVelocity;
        }

        if (!IsGrounded)
        {
            VerticalVelocity += Gravity * dt;
            VerticalOffset   += VerticalVelocity * dt;
            if (VerticalOffset >= 0.0 && VerticalVelocity > 0.0)
            {
                VerticalOffset   = 0.0;
                VerticalVelocity = 0.0;
                IsGrounded       = true;
                LandedThisFrame  = true;
            }
        }
    }

    /// <summary>状态重挂载时重置动力学，避免旧窗口速度泄漏到新舞台。</summary>
    public void Reset(double positionX)
    {
        PositionX        = double.IsFinite(positionX) ? positionX : 0.0;
        VelocityX        = 0.0;
        GaitPhase        = 0.0;
        TurnAnticipation = 0.0;
        VerticalOffset   = 0.0;
        VerticalVelocity = 0.0;
        IsGrounded       = true;
        LandedThisFrame  = false;
    }

    private static double MoveTowards(
        double current,
        double target,
        double maxDelta)
    {
        if (current < target)
        {
            return Math.Min(current + maxDelta, target);
        }

        if (current > target)
        {
            return Math.Max(current - maxDelta, target);
        }

        return current;
    }

    private static double Wrap01(double value)
    {
        value %= 1.0;
        return value < 0.0
            ? value + 1.0
            : value;
    }
}
