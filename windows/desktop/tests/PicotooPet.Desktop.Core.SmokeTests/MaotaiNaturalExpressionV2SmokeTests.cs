using System.Reflection;
using System.Threading;
using System.Windows.Controls;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 工作情绪与休息表情必须落到真实 Pose，而不是只切换状态名称。</summary>
internal static class MaotaiNaturalExpressionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;
    private static readonly Type PanelType = typeof(AssistantPetPanel);

    public static void Run()
    {
        VerifyWorkingExpressions();
        VerifyWorkingExpressionRendererBoundaryContinuity();
        VerifyAutonomousSleepExpression();
        VerifyWakeExpression();
        VerifySleepingPatCompletesAfterPulseExpires();
        VerifyOfflineCancelsDeferredSleepingPat();
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

    /// <summary>真实 WorkTyping -> WorkTired 首帧仍处于早期 graph transition，WPF 眼睛/嘴型图层不能 1↔0 闪切。</summary>
    private static void VerifyWorkingExpressionRendererBoundaryContinuity()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 43, 108.0)
            ?? throw new InvalidOperationException("无法创建工作表情边界 Motion Engine");

        object? previousPose = null;
        object? tiredPose    = null;
        for (var frame = 0; frame < 900; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateWorkingInput()])
                ?? throw new InvalidOperationException("工作表情边界测试没有输出 Pose");
            if (previousPose is not null &&
                ReadString(previousPose, "MotionState") == "WorkTyping" &&
                ReadString(pose, "MotionState") == "WorkTired")
            {
                tiredPose = pose;
                break;
            }

            previousPose = pose;
        }

        Assert(previousPose is not null && tiredPose is not null,
            "工作表情边界测试未在 900 帧内观察到 WorkTyping -> WorkTired");
        var transition = ReadDouble(tiredPose!, "MotionTransitionBlend");
        Assert(transition >= 0.0 && transition < 0.10,
            $"WorkTired 首个可见帧必须处于早期 graph transition；actual={transition:F3}");
        Assert(ReadString(previousPose!, "MouthState") == "Smile" &&
               ReadString(tiredPose!, "MouthState") == "Tired",
            "测试夹具必须覆盖 Smile -> Tired 真实工作表情边界");
        Assert(ReadString(previousPose!, "EyeState") == "Open" &&
               ReadString(tiredPose!, "EyeState") == "Half",
            "测试夹具必须覆盖 Open -> Half 真实工作眼态边界，不能碰巧落在自然眨眼帧");

        RunOnSta(() =>
        {
            var panel = new AssistantPetPanel();
            var buildVisuals = PanelType.GetMethod(
                "BuildMaotaiRasterVisuals",
                BindingFlags.Instance | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("AssistantPetPanel 缺少 BuildMaotaiRasterVisuals");
            var visuals = buildVisuals.Invoke(panel, null)
                ?? throw new InvalidOperationException("BuildMaotaiRasterVisuals 没有返回可见层集合");
            var rendererType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiRasterRenderer");
            var renderer = Activator.CreateInstance(rendererType, visuals)
                ?? throw new InvalidOperationException("无法创建工作表情边界 MaotaiRasterRenderer");
            var apply = rendererType.GetMethod(
                "Apply",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?? throw new InvalidOperationException("MaotaiRasterRenderer 缺少 Apply");

            var eyeOpen    = GetField<Image>(panel, "MaotaiV2EyeLeftOpen");
            var eyeHalf    = GetField<Image>(panel, "MaotaiV2EyeLeftHalf");
            var mouthSmile = GetField<Image>(panel, "MaotaiV2MouthSmile");
            var mouthTired = GetField<Image>(panel, "MaotaiV2MouthTired");

            apply.Invoke(renderer, [previousPose!]);
            var previousEyeOpen    = eyeOpen.Opacity;
            var previousEyeHalf    = eyeHalf.Opacity;
            var previousMouthSmile = mouthSmile.Opacity;
            var previousMouthTired = mouthTired.Opacity;

            apply.Invoke(renderer, [tiredPose!]);
            var eyeOpenDelta    = Math.Abs(eyeOpen.Opacity - previousEyeOpen);
            var eyeHalfDelta    = Math.Abs(eyeHalf.Opacity - previousEyeHalf);
            var mouthSmileDelta = Math.Abs(mouthSmile.Opacity - previousMouthSmile);
            var mouthTiredDelta = Math.Abs(mouthTired.Opacity - previousMouthTired);

            Assert(eyeOpenDelta <= 0.20 && eyeHalfDelta <= 0.20,
                $"WorkTyping -> WorkTired 眼睛图层不能单帧 Open/Half 互切；openDelta={eyeOpenDelta:F3}, halfDelta={eyeHalfDelta:F3}, transition={transition:F3}");
            Assert(mouthSmileDelta <= 0.20 && mouthTiredDelta <= 0.20,
                $"WorkTyping -> WorkTired 嘴型图层不能单帧 Smile/Tired 互切；smileDelta={mouthSmileDelta:F3}, tiredDelta={mouthTiredDelta:F3}, transition={transition:F3}");
        });
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

    /// <summary>从睡眠被用户唤醒时先半睁眼，再在起身阶段恢复正常睁眼；互动嘴型只能在起身完成后出现。</summary>
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
            var mouth  = ReadString(pose, "MouthState");

            if (motion == "Wake")
            {
                sawWake = true;
                Assert(eye == "Half",
                    $"Sleep -> Wake 必须先半睁眼，不能瞬间完全睁开；当前 EyeState={eye}");
                Assert(mouth != "Tongue",
                    $"Sleep -> Wake 仍在醒来阶段，互动 Tongue 不能提前出现；当前 MouthState={mouth}");
            }
            else if (motion == "GetUp")
            {
                Assert(mouth != "Tongue",
                    $"Wake -> GetUp 仍在起身阶段，互动 Tongue 不能提前出现；当前 MouthState={mouth}");
                if (eye == "Open")
                {
                    sawGetUpOpen = true;
                }
            }

            if (motion == "UserReaction")
            {
                break;
            }
        }

        Assert(sawWake, "睡眠交互未经过 Wake 表情阶段");
        Assert(sawGetUpOpen, "Wake 后的 GetUp 阶段必须恢复至少一帧正常睁眼");
    }

    /// <summary>真实单击 Pat 只有约 0.55 秒；一旦睡眠中的交互已被接受，起身链不能因原始输入过期而丢掉最终反应。</summary>
    private static void VerifySleepingPatCompletesAfterPulseExpires()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 67, 108.0)
            ?? throw new InvalidOperationException("无法创建睡眠 Pat 脉冲 Motion Engine");

        var reachedSleep = false;
        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(autonomousState: "Sleep")])
                ?? throw new InvalidOperationException("Pat 脉冲测试的睡眠阶段没有输出 Pose");
            if (ReadString(pose, "MotionState") == "Sleep")
            {
                reachedSleep = true;
                break;
            }
        }
        Assert(reachedSleep, "Pat 脉冲测试未先进入 Sleep");

        // UI click pulse      : AssistantPetPanel keeps Pat/Paw alive for 0.55 s, i.e. 33 frames at 60 Hz.
        for (var frame = 0; frame < 33; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(interaction: "Pat")])
                ?? throw new InvalidOperationException("Pat 脉冲阶段没有输出 Pose");
            Assert(ReadString(pose, "MotionState") != "UserReaction",
                "0.55 秒 Pat 脉冲必须先完成 Wake/GetUp，测试夹具不能在原始输入过期前提前进入 UserReaction");
        }

        var sawDeferredReaction = false;
        var sawDeferredTongue   = false;
        for (var frame = 0; frame < 90; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput()])
                ?? throw new InvalidOperationException("Pat 脉冲过期后的起身阶段没有输出 Pose");
            if (ReadString(pose, "MotionState") != "UserReaction")
            {
                continue;
            }

            sawDeferredReaction = true;
            sawDeferredTongue  |= ReadString(pose, "MouthState") == "Tongue";
        }

        Assert(sawDeferredReaction,
            "睡眠中已接受的 0.55 秒 Pat 不能在 Wake/GetUp 途中因输入过期而丢失 UserReaction");
        Assert(sawDeferredTongue,
            "延迟到起身完成后的 UserReaction 必须保留原 Pat 的 Tongue 可见反馈");
    }

    /// <summary>Offline/Error 属于强状态；一旦出现，必须丢弃尚未完成的睡眠互动，恢复后也不能补播旧反应。</summary>
    private static void VerifyOfflineCancelsDeferredSleepingPat()
    {
        var engineType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionEngine");
        var update     = RequireMethod(engineType, "Update");
        var engine     = Activator.CreateInstance(engineType, 71, 108.0)
            ?? throw new InvalidOperationException("无法创建 Offline 取消互动 Motion Engine");

        var reachedSleep = false;
        for (var frame = 0; frame < 360; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(autonomousState: "Sleep")])
                ?? throw new InvalidOperationException("Offline 取消测试的睡眠阶段没有输出 Pose");
            if (ReadString(pose, "MotionState") == "Sleep")
            {
                reachedSleep = true;
                break;
            }
        }
        Assert(reachedSleep, "Offline 取消互动测试未先进入 Sleep");

        var acceptedPose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(interaction: "Pat")])
            ?? throw new InvalidOperationException("Offline 取消测试没有接受 Pat");
        Assert(ReadString(acceptedPose, "MotionState") != "UserReaction",
            "睡眠 Pat 首帧必须先走 Wake/GetUp，不能让测试夹具直接进入 UserReaction");

        // Strong state         : one Offline frame is enough to revoke any cosmetic deferred click feedback.
        update.Invoke(engine, [1.0 / 60.0, CreateRestingInput(baseState: "Offline")]);

        for (var frame = 0; frame < 120; frame++)
        {
            var pose = update.Invoke(engine, [1.0 / 60.0, CreateRestingInput()])
                ?? throw new InvalidOperationException("Offline 恢复后的测试没有输出 Pose");
            Assert(ReadString(pose, "MotionState") != "UserReaction",
                "Offline 已取消的睡眠 Pat 在恢复后不能补播旧 UserReaction");
            Assert(ReadString(pose, "MouthState") != "Tongue",
                "Offline 已取消的睡眠 Pat 在恢复后不能泄漏旧 Tongue 表情");
        }
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
        string? autonomousState = null,
        string baseState = "Resting")
    {
        var baseType        = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiBaseState");
        var interactionType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiInteractionKind");
        var inputType       = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionInput");

        var input = Activator.CreateInstance(
            inputType,
            Enum.Parse(baseType, baseState),
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

    private static void RunOnSta(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception exception)
            {
                failure = exception;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();

        if (failure is not null)
        {
            throw new InvalidOperationException("Maotai 工作表情 Renderer 连续性 smoke failed.", failure);
        }
    }

    private static T GetField<T>(object target, string fieldName) where T : class =>
        PanelType.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(target) as T
        ?? throw new InvalidOperationException($"AssistantPetPanel 缺少字段 {fieldName} 或类型不是 {typeof(T).Name}");

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

    private static double ReadDouble(object value, string propertyName) =>
        (double)(RequireProperty(value.GetType(), propertyName).GetValue(value)
            ?? throw new InvalidOperationException($"{propertyName} 为空"));

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
