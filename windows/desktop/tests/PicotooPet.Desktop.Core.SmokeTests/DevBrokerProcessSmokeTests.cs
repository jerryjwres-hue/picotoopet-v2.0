using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.DevBroker;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证固定沙盒与无界面 Mock Provider 子进程合同。</summary>
internal static class DevBrokerProcessSmokeTests
{
    /// <summary>直接运行纯核心子进程逻辑，验证文件、变更和事件边界。</summary>
    public static void Run()
    {
        var sessionId = Guid.NewGuid().ToString("D");
        var handoffId = Guid.NewGuid().ToString("D");
        var paths     = BrokerSandboxPaths.FromLocalAppData(sessionId);
        var input = new MockBrokerSessionInput(
            "1.0.0",
            sessionId,
            handoffId,
            new string('a', 64),
            new string('b', 64),
            new string('c', 40));
        BrokerSandboxBuilder.Prepare(paths, input);
        File.WriteAllBytes(paths.StartGatePath, [1]);
        try
        {
            var envelope = MockProviderChild.Run(sessionId);
            Assert(envelope.SessionId == sessionId, "Mock Return Session 绑定错误");
            Assert(envelope.HandoffId == handoffId, "Mock Return Handoff 绑定错误");
            Assert(envelope.Provider == "local-mock-dev-broker", "Mock Provider 标签错误");
            Assert(envelope.Files.Count == 10, "Mock Return 文件数不是固定 10");
            Assert(
                envelope.Files.Select(file => file.Name).Distinct(StringComparer.Ordinal).Count() == 10,
                "Mock Return 文件名存在重复");
            Assert(
                envelope.Files.Any(file =>
                    file.Name == "changes/docs/mock-provider-proof.txt"),
                "Mock Return 缺少唯一允许的证明文本");

            var changed = JsonDocument.Parse(
                envelope.Files.Single(file => file.Name == "changed_files.json").Content);
            Assert(
                changed.RootElement.GetProperty("files").GetArrayLength() == 1,
                "Mock Return 变更数量不是 1");
            Assert(
                changed.RootElement.GetProperty("files")[0].GetProperty("path").GetString()
                    == "docs/mock-provider-proof.txt",
                "Mock Return 变更路径不是固定证明文本");

            var events = envelope.Files
                .Single(file => file.Name == "session_events.ndjson")
                .Content
                .Split('\n', StringSplitOptions.RemoveEmptyEntries);
            Assert(events.Length == 4, "Mock Return 事件数量不是 4");
            Assert(
                events.Select(line => JsonDocument.Parse(line).RootElement
                        .GetProperty("sequence").GetInt32())
                    .SequenceEqual([1, 2, 3, 4]),
                "Mock Return 事件顺序不连续");
            Assert(File.Exists(paths.ReturnEnvelopePath), "Mock Return 信封未写入固定沙盒");
        }
        finally
        {
            BrokerSandboxBuilder.Cleanup(paths);
        }

        var processSessionId = Guid.NewGuid().ToString("D");
        var processPaths     = BrokerSandboxPaths.FromLocalAppData(processSessionId);
        BrokerSandboxBuilder.Prepare(
            processPaths,
            new MockBrokerSessionInput(
                "1.0.0",
                processSessionId,
                Guid.NewGuid().ToString("D"),
                new string('d', 64),
                new string('e', 64),
                new string('f', 40)));
        File.WriteAllBytes(processPaths.StartGatePath, [1]);
        using var successOutput = new StringWriter();
        using var successError  = new StringWriter();
        try
        {
            Assert(
                MockProviderChild.TryRun(
                    ["--dev-broker-mock-child", "--session-id", processSessionId],
                    successOutput,
                    successError,
                    out var successExitCode),
                "有效子进程参数未进入 Broker 模式");
            Assert(successExitCode == 0, "有效子进程返回失败状态");
            Assert(
                successOutput.ToString().Length == 0,
                "成功子进程不得再通过 stdout 传输含本地化文本的 Return Envelope");
            Assert(successError.ToString().Length == 0, "成功子进程写入了错误输出");
            Assert(
                File.Exists(processPaths.ReturnEnvelopePath),
                "成功子进程未写入固定 Return 文件");
        }
        finally
        {
            BrokerSandboxBuilder.Cleanup(processPaths);
        }

        using var output = new StringWriter();
        using var error  = new StringWriter();
        Assert(
            MockProviderChild.TryRun(
                ["--dev-broker-mock-child", "--session-id", "../outside"],
                output,
                error,
                out var exitCode),
            "非法子进程参数未被识别为 Broker 模式");
        Assert(exitCode != 0, "非法子进程参数未返回失败状态");
        Assert(output.ToString().Length == 0, "非法参数泄漏了标准输出");
        Assert(error.ToString().Trim() == "BROKER_OUTPUT_INVALID", "错误输出不是固定错误码");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
