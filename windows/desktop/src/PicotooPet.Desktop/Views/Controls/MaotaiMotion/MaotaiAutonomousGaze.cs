namespace PicotooPet.Desktop.Views.Controls.MaotaiMotion;

/// <summary>待机时的微小自主视线；鼠标进入后立即让位，不创建第二套行为状态机。</summary>
internal static class MaotaiAutonomousGaze
{
    public static (double X, double Y) Resolve(
        bool pointerInside,
        double pointerX,
        double pointerY,
        bool allowAutonomous,
        double elapsedSeconds,
        double seedPhaseRadians)
    {
        if (pointerInside)
        {
            return (
                Math.Clamp(pointerX, -1.0, 1.0) * 1.9,
                Math.Clamp(pointerY, -1.0, 1.0) * 1.1);
        }

        if (!allowAutonomous ||
            !double.IsFinite(elapsedSeconds) ||
            !double.IsFinite(seedPhaseRadians))
        {
            return (0.0, 0.0);
        }

        // Two incommensurate slow waves prevent a robotic left-right metronome while remaining deterministic.
        var x = (Math.Sin((elapsedSeconds * 0.53) + seedPhaseRadians) * 0.62) +
                (Math.Sin((elapsedSeconds * 0.19) + (seedPhaseRadians * 1.7)) * 0.28);
        var y = (Math.Sin((elapsedSeconds * 0.41) + (seedPhaseRadians * 0.7)) * 0.28) +
                (Math.Sin((elapsedSeconds * 0.17) + (seedPhaseRadians * 1.2)) * 0.12);

        return (
            Math.Clamp(x, -0.90, 0.90),
            Math.Clamp(y, -0.42, 0.42));
    }
}
