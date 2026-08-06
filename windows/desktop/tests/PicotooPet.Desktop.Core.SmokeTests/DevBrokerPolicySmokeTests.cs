using System.Reflection;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.DevBroker;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>锁定 Mock Dev Broker 的固定动作、沙盒和安全投影边界。</summary>
internal static class DevBrokerPolicySmokeTests
{
    /// <summary>验证没有字符串命令、任意路径或外部 Provider 入口。</summary>
    public static void Run()
    {
        Assert(
            BrokerCommandPolicy.IsAllowed(BrokerAction.RunMockProvider),
            "固定 Mock Provider 动作未被允许");
        Assert(
            !BrokerCommandPolicy.IsAllowed((BrokerAction)999),
            "未登记 Broker 动作未被拒绝");

        var forbiddenStringParameters = typeof(BrokerCommandPolicy)
            .GetMethods(BindingFlags.Public | BindingFlags.Static)
            .SelectMany(method => method.GetParameters())
            .Where(parameter => parameter.ParameterType == typeof(string))
            .ToArray();
        Assert(
            forbiddenStringParameters.Length == 0,
            "Broker 命令策略暴露了字符串命令入口");

        var sessionId = Guid.NewGuid().ToString("D");
        var paths     = BrokerSandboxPaths.FromLocalAppData(sessionId);
        var localRoot = Path.GetFullPath(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData));
        Assert(
            paths.Root.StartsWith(localRoot, StringComparison.OrdinalIgnoreCase),
            "Broker 沙盒逃离 LocalAppData");
        Assert(
            paths.ProofRelativePath == "docs/mock-provider-proof.txt",
            "Broker 唯一允许变更路径发生漂移");
        AssertThrows<ArgumentException>(
            () => BrokerSandboxPaths.FromLocalAppData("../outside"),
            "Broker Session ID 未拒绝路径逃逸");

        var record = new BrokerSessionRecord(
            sessionId,
            Guid.NewGuid().ToString("D"),
            "reserved",
            "local-mock-dev-broker",
            30,
            new string('a', 64),
            new string('b', 64),
            null,
            0,
            null,
            null,
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow,
            null,
            "固定 Mock Provider 安全验证。");
        Assert(record.Provider == "local-mock-dev-broker", "Broker Provider 不是固定值");
        Assert(record.TimeoutSeconds == 30, "Broker 超时不是固定 30 秒");
    }

    private static void AssertThrows<TException>(Action action, string message)
        where TException : Exception
    {
        try
        {
            action();
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
