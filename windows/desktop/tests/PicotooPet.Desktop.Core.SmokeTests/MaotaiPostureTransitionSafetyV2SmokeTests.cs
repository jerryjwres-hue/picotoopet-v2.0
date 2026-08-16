using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证高速自主移动切换到坐/趴时必须先刹停并走合法中间 Pose，禁止“滑着坐下”。</summary>
internal static class MaotaiPostureTransitionSafetyV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyRunToSitStopsBeforePosture();
        VerifyRunToLieDownUsesSitBridgeAfterStop();
    }

    private static void VerifyRunToSitStopsBeforePosture()
    {
        var harness = CreateRunningEngine(seed: 131);
        var stopTarget = ReadDouble(harness.Engine, "PositionX");
        var sitInput = CreateInput(stopTarget, wantsRun: false, autonomousState: "Sit");
        var sawWalk = false;
        var sawIdle = false;
        var reachedSit = false;

        for (var frame = 0; frame < 180; frame++)
        {
            var pose = harness.Update.Invoke(harness.Engine, [1.0 / 60.0, sitInput])
                ?? throw new InvalidOperationException("Run→Sit 没有输出 Pose");
            var state = ReadProperty(pose, "MotionState").ToString();
            var speed = Math.Abs(ReadLocomotionVelocity(harness.Engine));

            sawWalk |= string.Equals(state, "Walk", StringComparison.Ordinal);
            sawIdle |= string.Equals(state, "Idle", StringComparison.Ordinal);
            if (!string.Equals(state, "Sit", StringComparison.Ordinal))
            {
                continue;
            }

            reachedSit = true;
            Assert(speed <= 3.0,
                $"Run→Sit 在仍有 {speed:F2} 速度时已经进入坐姿，会出现滑着坐下");
            break;
        }

        Assert(reachedSit, "Run→Sit 在 3 秒内没有完成");
        Assert(sawWalk && sawIdle,
            "Run→Sit 必须经过 Walk→Idle 刹停桥接，不能从跑姿直接瞬切 Sit");
    }

    private static void VerifyRunToLieDownUsesSitBridgeAfterStop()
    {
        var harness = CreateRunningEngine(seed: 137);
        var stopTarget = ReadDouble(harness.Engine, "PositionX");
        var lieInput = CreateInput(stopTarget, wantsRun: false, autonomousState: "LieDown");
        var sawWalk = false;
        var sawIdle = false;
        var sawSit = false;
        var reachedLieDown = false;

        for (var frame = 0; frame < 240; frame++)
        {
            var pose = harness.Update.Invoke(harness.Engine, [1.0 / 60.0, lieInput])
                ?? throw new InvalidOperationException("Run→LieDown 没有输出 Pose");
            var state = ReadProperty(pose, "MotionState").ToString();
            var speed = Math.Abs(ReadLocomotionVelocity(harness.Engine));

            sawWalk |= string.Equals(state, "Walk", StringComparison.Ordinal);
            sawIdle |= string.Equals(state, "Idle", StringComparison.Ordinal);
            if (string.Equals(state, "Sit", StringComparison.Ordinal))
            {
                sawSit = true;
                Assert(speed <= 3.0,
                    $"Run→LieDown 在仍有 {speed:F2} 速度时已经进入坐姿桥接，会出现滑行压缩身体");
            }

            if (!string.Equals(state, "LieDown", StringComparison.Ordinal))
            {
                continue;
            }

            reachedLieDown = true;
            Assert(speed <= 3.0,
                $"Run→LieDown 在仍有 {speed:F2} 速度时已经进入趴姿");
            break;
        }

        Assert(reachedLieDown, "Run→LieDown 在 4 秒内没有完成");
        Assert(sawWalk && sawIdle && sawSit,
            "Run→LieDown 必须经过 Walk→Idle→Sit 再趴下，禁止高速直接 LieDown");
    }

    private static EngineHarness CreateRunningEngine(int seed)
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update = engineType.GetMethod("Update", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 Update");
        var engine = Activator.CreateInstance(engineType, seed, 34.0)
            ?? throw new InvalidOperationException("无法创建 MaotaiMotionEngine");
        var runInput = CreateInput(146.0, wantsRun: true, autonomousState: null);

        for (var frame = 0; frame < 120; frame++)
        {
            _ = update.Invoke(engine, [1.0 / 60.0, runInput]);
            var state = ReadProperty(engine, "ActiveState").ToString();
            var speed = Math.Abs(ReadLocomotionVelocity(engine));
            if (string.Equals(state, "Run", StringComparison.Ordinal) && speed >= 55.0)
            {
                return new EngineHarness(engine, update);
            }
        }

        throw new InvalidOperationException(
            $"姿态安全测试没有建立高速 Run；state={ReadProperty(engine, "ActiveState")}, velocity={ReadLocomotionVelocity(engine):F2}");
    }

    private static object CreateInput(
        double targetX,
        bool wantsRun,
        string? autonomousState)
    {
        var inputType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");
        var baseStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var motionStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var input = Activator.CreateInstance(
            inputType,
            [
                Enum.Parse(baseStateType, "Resting"),
                0.0,
                0.0,
                false,
                Enum.Parse(interactionType, "None"),
                18.0,
                150.0,
                targetX,
                wantsRun,
                false,
                70.0,
            ]) ?? throw new InvalidOperationException("无法创建 MaotaiMotionInput");

        if (autonomousState is not null)
        {
            var property = inputType.GetProperty(
                "AutonomousState",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("MaotaiMotionInput 缺少 AutonomousState");
            property.SetValue(input, Enum.Parse(motionStateType, autonomousState));
        }

        return input;
    }

    private static double ReadLocomotionVelocity(object engine)
    {
        var field = engine.GetType().GetField(
            "_locomotion",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("MaotaiMotionEngine 缺少 _locomotion");
        var locomotion = field.GetValue(engine)
            ?? throw new InvalidOperationException("_locomotion 为空");
        return ReadDouble(locomotion, "VelocityX");
    }

    private static object ReadProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target)
        ?? throw new InvalidOperationException($"{target.GetType().Name} 缺少属性 {name}");

    private static double ReadDouble(object target, string name) =>
        Convert.ToDouble(ReadProperty(target, name), System.Globalization.CultureInfo.InvariantCulture);

    private static Type RequireType(string name) =>
        DesktopAssembly.GetType(name, throwOnError: true)!;

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private readonly record struct EngineHarness(object Engine, MethodInfo Update);
}
