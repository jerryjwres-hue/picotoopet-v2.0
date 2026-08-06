using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>只在应用自有 LocalAppData 根中创建固定 Mock Provider 沙盒。</summary>
public static class BrokerSandboxBuilder
{
    private static readonly UTF8Encoding Utf8NoBom = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        WriteIndented          = false,
    };

    /// <summary>创建确定性 fixture/workspace 并写入不含秘密的 Session 输入。</summary>
    public static void Prepare(
        BrokerSandboxPaths paths,
        MockBrokerSessionInput sessionInput)
    {
        ArgumentNullException.ThrowIfNull(paths);
        ArgumentNullException.ThrowIfNull(sessionInput);
        ValidateSessionInput(paths, sessionInput);
        RejectExistingReparsePoint(paths.Root);

        if (Directory.Exists(paths.Root))
        {
            Directory.Delete(paths.Root, recursive: true);
        }

        Directory.CreateDirectory(Path.Combine(paths.FixtureRoot, "docs"));
        Directory.CreateDirectory(Path.Combine(paths.WorkspaceRoot, "docs"));
        Directory.CreateDirectory(paths.ReturnRoot);

        WriteText(
            Path.Combine(paths.FixtureRoot, "project.json"),
            "{\"name\":\"picotoopet-mock-fixture\",\"schema_version\":\"1.0.0\"}\n");
        WriteText(
            Path.Combine(paths.FixtureRoot, "docs", "README.md"),
            "# PicotooPet Mock Broker Fixture\n");
        File.Copy(
            Path.Combine(paths.FixtureRoot, "project.json"),
            Path.Combine(paths.WorkspaceRoot, "project.json"),
            overwrite: false);
        File.Copy(
            Path.Combine(paths.FixtureRoot, "docs", "README.md"),
            Path.Combine(paths.WorkspaceRoot, "docs", "README.md"),
            overwrite: false);
        WriteText(
            paths.SessionInputPath,
            JsonSerializer.Serialize(sessionInput, JsonOptions) + "\n");
        RejectExistingReparsePoint(paths.Root);
    }

    /// <summary>删除一个规范 Session 沙盒；拒绝跟随 reparse point。</summary>
    public static void Cleanup(BrokerSandboxPaths paths)
    {
        ArgumentNullException.ThrowIfNull(paths);
        if (!Directory.Exists(paths.Root) && !File.Exists(paths.Root))
        {
            return;
        }
        RejectExistingReparsePoint(paths.Root);
        Directory.Delete(paths.Root, recursive: true);
    }

    /// <summary>拒绝目标路径及其已存在子目录中的 reparse point。</summary>
    public static void RejectExistingReparsePoint(string root)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(root);
        var fullRoot = Path.GetFullPath(root);
        if (File.Exists(fullRoot))
        {
            throw new InvalidOperationException("Broker 沙盒根不能是文件。 ");
        }
        if (!Directory.Exists(fullRoot))
        {
            return;
        }

        RejectReparseAttribute(fullRoot);
        foreach (var directory in Directory.EnumerateDirectories(
                     fullRoot,
                     "*",
                     SearchOption.AllDirectories))
        {
            RejectReparseAttribute(directory);
        }
        foreach (var file in Directory.EnumerateFiles(
                     fullRoot,
                     "*",
                     SearchOption.AllDirectories))
        {
            RejectReparseAttribute(file);
        }
    }

    private static void ValidateSessionInput(
        BrokerSandboxPaths paths,
        MockBrokerSessionInput input)
    {
        var expectedSession = Path.GetFileName(paths.Root);
        if (!string.Equals(input.SchemaVersion, "1.0.0", StringComparison.Ordinal)
            || !string.Equals(input.SessionId, expectedSession, StringComparison.Ordinal)
            || !Guid.TryParseExact(input.SessionId, "D", out _)
            || !Guid.TryParseExact(input.HandoffId, "D", out _)
            || !IsSha256(input.RequestDigest)
            || !IsSha256(input.PackageDigest)
            || !IsSha256(input.BaseCommit))
        {
            throw new ArgumentException("Broker Session 输入不符合固定安全合同。", nameof(input));
        }
    }

    private static bool IsSha256(string value) =>
        value.Length == 64 && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void RejectReparseAttribute(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidOperationException("Broker 沙盒拒绝 reparse point。 ");
        }
    }

    private static void WriteText(string path, string content) =>
        File.WriteAllText(path, content, Utf8NoBom);
}
