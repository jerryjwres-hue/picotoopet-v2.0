namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>从受信任 LocalAppData 根和规范 UUID 推导固定 Broker 沙盒路径。</summary>
public sealed record BrokerSandboxPaths(
    string Root,
    string FixtureRoot,
    string WorkspaceRoot,
    string ReturnRoot,
    string SessionInputPath,
    string StartGatePath,
    string ReturnEnvelopePath)
{
    /// <summary>唯一允许的工作区相对变更路径。</summary>
    public const string ProofRelativePath = "docs/mock-provider-proof.txt";

    /// <summary>根据当前用户 LocalAppData 创建固定路径投影，不访问文件系统。</summary>
    public static BrokerSandboxPaths FromLocalAppData(string sessionId)
    {
        if (!Guid.TryParseExact(sessionId, "D", out var parsedSession))
        {
            throw new ArgumentException("Broker Session ID 必须是规范 UUID。", nameof(sessionId));
        }

        var localAppData = Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData,
            Environment.SpecialFolderOption.DoNotVerify);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            throw new InvalidOperationException("无法解析当前用户 LocalAppData。");
        }

        var trustedRoot = Path.GetFullPath(Path.Combine(
            localAppData,
            "PicotooPetV2",
            "DevBroker",
            "sessions"));
        var sessionRoot = Path.GetFullPath(Path.Combine(
            trustedRoot,
            parsedSession.ToString("D")));
        var prefix = trustedRoot.EndsWith(Path.DirectorySeparatorChar)
            ? trustedRoot
            : trustedRoot + Path.DirectorySeparatorChar;
        if (!sessionRoot.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Broker 沙盒路径越过固定 LocalAppData 根。");
        }

        return new BrokerSandboxPaths(
            sessionRoot,
            Path.Combine(sessionRoot, "fixture", "base"),
            Path.Combine(sessionRoot, "workspace"),
            Path.Combine(sessionRoot, "return"),
            Path.Combine(sessionRoot, "session-input.json"),
            Path.Combine(sessionRoot, "start.ready"),
            Path.Combine(sessionRoot, "return", "return-envelope.json"));
    }
}
