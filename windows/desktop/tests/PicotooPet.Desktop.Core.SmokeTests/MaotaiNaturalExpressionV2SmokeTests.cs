using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台 v2 工作情绪必须落到真实 Pose，而不是只切换状态名称。</summary>
internal static class MaotaiNaturalExpressionV2SmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
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
