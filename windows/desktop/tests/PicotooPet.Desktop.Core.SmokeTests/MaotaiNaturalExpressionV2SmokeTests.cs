using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 工作情绪与休息表情必须落到真实 Pose，而不是只切换状态名称。</summary>
internal static class MaotaiNaturalExpressionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        VerifyWorkingExpressions();
        VerifyAutonomousSleepExpression();
        VerifyWakeExpression();
    }

    /// <summary>工作情绪必须驱动真实眼睛和嘴型图层。</summary>
    private static void VerifyWorkingExpressions()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 43, 108.0)
            ?? throw new InvalidOperationException("无法创建自然表情 Motion Engine");

        var sawTiredExpression   = false;
        var sawYawnExpression    = false;
        var sawAnnoyedExpression = false;
        var sawRecoverExpression = false;

        for (var frame = 0; frame < 1800; frame++)
        {
            var input = CreateWorkingInput();
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("自然表情测试没有输出 Pose");
            var motion = ReadString(pose, "MotionState");
            var eye    = ReadString(pose, "EyeState");
            var mouth  = ReadString(pose, "MouthState");

            if (motion == "WorkTired")
            {
                sawTiredExpression |= eye == "Half" && mouth == "Tired";
            }
            else if (motion == "Yawn")
            {
                sawYawnExpression |= eye == "Closed" && mouth == "Yawn";
            }
            else if (motion == "WorkAnnoyed")
            {
                sawAnnoyedExpression |= eye == "Half" && mouth == "Annoyed";
            }
            else if (motion == "Recover")
            {
                sawRecoverExpression |= eye == "Open" && mouth == "Smile";
            }
        }

        Assert(sawTiredExpression,
            "WorkTired 必须使用半闭眼 + 疲惫嘴型，不能只是状态名变化");
        Assert(sawYawnExpression,
            "Yawn 必须使用闭眼 + 哈欠嘴型，不能整图闪切");
        Assert(sawAnnoyedExpression,
            "WorkAnnoyed 必须使用半眯眼 + 烦躁嘴型");
        Assert(sawRecoverExpression,
            "Recover 必须平滑回到睁眼 + 微笑基准表情");
    }

    /// <summary>自主小睡必须真正闭眼并使用放松嘴型，不能继续沿用普通待机微笑。</summary>
    private static void VerifyAutonomousSleepExpression()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 59, 108.0)
            ?? throw new InvalidOperationException("无法创建自主睡眠表情 Motion Engine");

        var sawSleep = false;
        for (var frame = 0; frame < 360; frame++)
        {
            var input = CreateRestingInput(autonomousState: "Sleep");
            var pose = update.Invoke(engine, [1.0 / 60.0, input])
                ?? throw new InvalidOperationException("自主睡眠表情测试没有输出 Pose");
            var motion = ReadString(pose, "MotionState");
            if (motion != "Sleep")
            {
                continue;
            }

            sawSleep = true;
            var eye   = ReadString(pose, "EyeState");
            var mouth = ReadString(pose, "MouthState");
            Assert(eye == "Closed",
                $"Resting 自主 Sleep 必须稳定闭眼；当前 EyeState={eye}");
            Assert(mouth == "Tired",
                $"Resting 自主 Sleep 必须使用放松疲惫嘴型，不能保持待机微笑；当前 MouthState={mouth}");
        }

        Assert(sawSleep, "自主睡眠表情测试未在 360 帧内进入 Sleep");
    }

    /// <summary>从睡眠被用户唤醒时先半睁眼，再在起身阶段恢复正常睁眼。</summary>
    private static void VerifyWakeExpression()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 61, 108.0)
            ?? throw new InvalidOperationException("无法创建唤醒表情 Motion Engine");

        var reachedSleep = false;
        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(autonomousState: "Sleep")])
                ?? throw new InvalidOperationException("唤醒前睡眠测试没有输出 Pose");
            if (ReadString(pose, "MotionState") == "Sleep")
            {
                reachedSleep = true;
                break;
            }
        }
        Assert(reachedSleep, "唤醒表情测试未先进入 Sleep");

        var sawWake      = false;
        var sawGetUpOpen = false;
        for (var frame = 0; frame < 180; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(interaction: "Pat")])
                ?? throw new InvalidOperationException("唤醒表情测试没有输出 Pose");
            var motion = ReadString(pose, "MotionState");
            var eye    = ReadString(pose, "EyeState");

            if (motion == "Wake")
            {
                sawWake = true;
                Assert(eye == "Half",
                    $"Sleep -> Wake 必须先半睁眼，不能瞬间完全睁开；当前 EyeState={eye}");
            }
            else if (motion == "GetUp" && eye == "Open")
            {
                sawGetUpOpen = true;
            }

            if (motion == "UserReaction")
            {
                break;
            }
        }

        Assert(sawWake, "睡眠交互未经过 Wake 表情阶段");
        Assert(sawGetUpOpen, "Wake 后的 GetUp 阶段必须恢复至少一帧正常睁眼");
    }

    private static object CreateWorkingInput()
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        return Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, "Working"),
            0.0,
            -0.1,
            true,
            Enum.Parse(interactionType, "None"),
            20.0,
            140.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 Working MotionInput");
    }

    private static object CreateRestingInput(
        string interaction = "None",
        string? autonomousState = null)
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        var input = Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, "Resting"),
            0.0,
            -0.1,
            false,
            Enum.Parse(interactionType, interaction),
            20.0,
            140.0,
            108.0,
            false,
            false,
            108.0)
            ?? throw new InvalidOperationException("无法创建 Resting MotionInput");

        if (autonomousState is not null)
        {
            var motionStateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
            RequireProperty(inputType, "AutonomousState").SetValue(
                input,
                Enum.Parse(motionStateType, autonomousState));
        }

        return input;
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");

    private static MethodInfo RequireMethod(Type type, string name) =>
        type.GetMethod(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少方法 {name}");

    private static PropertyInfo RequireProperty(Type type, string name) =>
        type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance) ??
        throw new InvalidOperationException($"{type.Name} 缺少属性 {name}");

    private static string ReadString(object value, string propertyName) =>
        RequireProperty(value.GetType(), propertyName).GetValue(value)?.ToString() ?? string.Empty;

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
