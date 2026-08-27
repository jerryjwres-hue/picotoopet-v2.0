namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>两段骨骼 IK 的稳定解析解。</summary>
internal readonly record struct MaotaiTwoBoneSolution(
    double UpperAngleDeg,
    double LowerAngleDeg,
    double JointX,
    double JointY,
    double EndX,
    double EndY,
    double EndError);

/// <summary>用于腿部落脚与工作前爪键盘定位的两段解析 IK。</summary>
internal static class MaotaiIkSolver
{
    private const double Epsilon = 0.000001;

    public static MaotaiTwoBoneSolution SolveTwoBone(
        double rootX,
        double rootY,
        double upperLength,
        double lowerLength,
        double targetX,
        double targetY,
        int bendSign)
    {
        if (!double.IsFinite(rootX) ||
            !double.IsFinite(rootY) ||
            !double.IsFinite(upperLength) ||
            !double.IsFinite(lowerLength) ||
            !double.IsFinite(targetX) ||
            !double.IsFinite(targetY) ||
            upperLength <= 0 ||
            lowerLength <= 0)
        {
            return default;
        }

        var dx       = targetX - rootX;
        var dy       = targetY - rootY;
        var distance = Math.Sqrt((dx * dx) + (dy * dy));

        if (distance < Epsilon)
        {
            dx       = 1.0;
            dy       = 0.0;
            distance = 1.0;
        }

        var minimumReach    = Math.Abs(upperLength - lowerLength) + Epsilon;
        var maximumReach    = upperLength + lowerLength - Epsilon;
        var clampedDistance = Math.Clamp(distance, minimumReach, maximumReach);
        var directionX      = dx / distance;
        var directionY      = dy / distance;
        var clampedTargetX  = rootX + (directionX * clampedDistance);
        var clampedTargetY  = rootY + (directionY * clampedDistance);

        var along = (
            (upperLength * upperLength) -
            (lowerLength * lowerLength) +
            (clampedDistance * clampedDistance)) /
            (2.0 * clampedDistance);
        var heightSquared  = Math.Max(
            0.0,
            (upperLength * upperLength) - (along * along));
        var height         = Math.Sqrt(heightSquared);
        var normalizedBend = bendSign >= 0 ? 1.0 : -1.0;

        var baseX  = rootX + (directionX * along);
        var baseY  = rootY + (directionY * along);
        var jointX = baseX + (-directionY * height * normalizedBend);
        var jointY = baseY + (directionX * height * normalizedBend);

        var upperAngle = Math.Atan2(jointY - rootY, jointX - rootX);
        var lowerAngle = Math.Atan2(clampedTargetY - jointY, clampedTargetX - jointX);
        var endX       = jointX + (Math.Cos(lowerAngle) * lowerLength);
        var endY       = jointY + (Math.Sin(lowerAngle) * lowerLength);
        var endErrorX  = endX - clampedTargetX;
        var endErrorY  = endY - clampedTargetY;
        var endError   = Math.Sqrt((endErrorX * endErrorX) + (endErrorY * endErrorY));

        return new MaotaiTwoBoneSolution(
            RadiansToDegrees(upperAngle),
            RadiansToDegrees(lowerAngle),
            jointX,
            jointY,
            endX,
            endY,
            endError);
    }

    private static double RadiansToDegrees(double radians) =>
        radians * (180.0 / Math.PI);
}
