using System.Reflection;
using PicotooPet.Desktop.Views.Controls;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结茅台坐下、趴下、睡眠、醒来和起身的合法连续过渡链。</summary>
internal static class MaotaiRestTransitionSmokeTests
{
    private static readonly Assembly DesktopAssembly = typeof(AssistantPetPanel).Assembly;

    public static void Run()
    {
        var stateType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiMotionState");
        var graphType = RequireType("PicotooPet.Desktop.Views.Controls.MaotaiMotion.MaotaiAnimationGraph");
        var request   = graphType.GetMethod("Request", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 Request");
        var update = graphType.GetMethod("Update", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 Update");
        var active = graphType.GetProperty("ActiveState", BindingFlags.Public | BindingFlags.Instance)
            ?? throw new InvalidOperationException("AnimationGraph 缺少 ActiveState");

        var idle  = Enum.Parse(stateType, "Idle");
        var sleep = Enum.Parse(stateType, "Sleep");
        var graph = Activator.CreateInstance(graphType, idle)
            ?? throw new InvalidOperationException("无法创建休息 AnimationGraph");

        request.Invoke(graph, [sleep]);
        var sleepChain = CaptureUntil(
            graph,
            update,
            active,
            terminalState: "Sleep",
            maxFrames: 300);
        AssertSequence(
            sleepChain,
            ["Sit", "LieDown", "Sleep"],
            "Idle -> Sleep 必须经过 Sit / LieDown，禁止姿态硬切");

        request.Invoke(graph, [idle]);
        var wakeChain = CaptureUntil(
            graph,
            update,
            active,
            terminalState: "Idle",
            maxFrames: 300);
        AssertSequence(
            wakeChain,
            ["Wake", "GetUp", "Idle"],
            "Sleep -> Idle 必须经过 Wake / GetUp，禁止瞬间起身");
    }

    private static List<string> CaptureUntil(
        object graph,
        MethodInfo update,
        PropertyInfo active,
        string terminalState,
        int maxFrames)
    {
        var states = new List<string>(8);
        var last   = string.Empty;

        for (var frame = 0; frame < maxFrames; frame++)
        {
            var state = active.GetValue(graph)?.ToString() ?? string.Empty;
            if (!string.Equals(state, last, StringComparison.Ordinal))
            {
                states.Add(state);
                last = state;
            }

            if (string.Equals(state, terminalState, StringComparison.Ordinal))
            {
                return states;
            }

            update.Invoke(graph, [1.0 / 60.0]);
        }

        throw new InvalidOperationException($"AnimationGraph 未在 {maxFrames} 帧内到达 {terminalState}");
    }

    private static void AssertSequence(
        IReadOnlyList<string> actual,
        IReadOnlyList<string> expected,
        string message)
    {
        var searchIndex = 0;
        foreach (var state in actual)
        {
            if (searchIndex < expected.Count &&
                string.Equals(state, expected[searchIndex], StringComparison.Ordinal))
            {
                searchIndex++;
            }
        }

        if (searchIndex != expected.Count)
        {
            throw new InvalidOperationException(
                $"{message}; actual={string.Join(" -> ", actual)}");
        }
    }

    private static Type RequireType(string fullName) =>
        DesktopAssembly.GetType(fullName) ??
        throw new InvalidOperationException($"缺少类型 {fullName}");
}
