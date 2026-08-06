using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.DevBroker;

/// <summary>同一预编译 EXE 的无界面固定 Mock Provider 子进程入口。</summary>
public static class MockProviderChild
{
    private const string ChildFlag     = "--dev-broker-mock-child";
    private const string SessionFlag   = "--session-id";
    private const int MaxInputBytes    = 8 * 1024;
    private const string Provider      = "local-mock-dev-broker";
    private const string SchemaVersion = "1.0.0";

    private static readonly string[] SecurityChecks = ["sandbox", "secret_scan"];

    private static readonly UTF8Encoding Utf8NoBom = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        Encoder       = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = false,
    };

    /// <summary>识别并执行固定子进程模式；普通 WPF 启动返回 false。</summary>
    public static bool TryRun(
        string[] args,
        TextWriter standardOutput,
        TextWriter standardError,
        out int exitCode)
    {
        ArgumentNullException.ThrowIfNull(args);
        ArgumentNullException.ThrowIfNull(standardOutput);
        ArgumentNullException.ThrowIfNull(standardError);
        exitCode = 0;
        if (!args.Contains(ChildFlag, StringComparer.Ordinal))
        {
            return false;
        }

        try
        {
            var sessionId = ParseSessionId(args);
            var envelope  = Run(sessionId);
            standardOutput.Write(JsonSerializer.Serialize(envelope, JsonOptions));
            standardOutput.Write('\n');
            exitCode = 0;
        }
        catch (ArgumentException)
        {
            standardError.WriteLine("BROKER_OUTPUT_INVALID");
            exitCode = 2;
        }
        catch (InvalidDataException)
        {
            standardError.WriteLine("BROKER_OUTPUT_INVALID");
            exitCode = 3;
        }
        catch (IOException)
        {
            standardError.WriteLine("BROKER_SANDBOX_IO_FAILED");
            exitCode = 4;
        }
        catch (UnauthorizedAccessException)
        {
            standardError.WriteLine("BROKER_SANDBOX_ACCESS_DENIED");
            exitCode = 5;
        }
        catch (CryptographicException)
        {
            standardError.WriteLine("BROKER_DIGEST_FAILED");
            exitCode = 6;
        }
        return true;
    }

    /// <summary>从固定沙盒读取安全事实并生成一个文本变更与严格 Return 信封。</summary>
    public static MockBrokerReturnEnvelope Run(string sessionId)
    {
        var paths = BrokerSandboxPaths.FromLocalAppData(sessionId);
        BrokerSandboxBuilder.RejectExistingReparsePoint(paths.Root);
        var input = ReadSessionInput(paths.SessionInputPath);
        ValidateInput(input, sessionId);

        var returnId = Guid.NewGuid().ToString("D");
        var proof = string.Join(
            '\n',
            "PicotooPet Mock Provider proof",
            $"session={input.SessionId}",
            $"package={input.PackageDigest}",
            string.Empty);
        var proofPath = Path.Combine(
            paths.WorkspaceRoot,
            "docs",
            "mock-provider-proof.txt");
        File.WriteAllText(proofPath, proof, Utf8NoBom);

        var sandboxDigest  = ComputeSandboxDigest(paths, proof);
        var entries        = BuildBaseEntries(input, returnId, proof);
        var manifestDigest = ComputeContentManifestDigest(entries);
        entries["return_manifest.json"] = SerializeFile(new SortedDictionary<string, object?>
        {
            ["base_commit"]        = input.BaseCommit,
            ["changed_file_count"] = 1,
            ["handoff_id"]         = input.HandoffId,
            ["manifest_digest"]    = manifestDigest,
            ["package_digest"]     = input.PackageDigest,
            ["provider"]           = Provider,
            ["request_digest"]     = input.RequestDigest,
            ["return_id"]          = returnId,
            ["sandbox_digest"]     = sandboxDigest,
            ["schema_version"]     = SchemaVersion,
            ["session_id"]         = input.SessionId,
        });
        entries["signatures/manifest.sha256"] = BuildSignature(entries);

        var files = entries
            .OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => new BrokerReturnFileRecord(pair.Key, pair.Value))
            .ToArray();
        var envelope = new MockBrokerReturnEnvelope(
            SchemaVersion,
            input.SessionId,
            input.HandoffId,
            returnId,
            Provider,
            input.RequestDigest,
            input.PackageDigest,
            sandboxDigest,
            files);
        Directory.CreateDirectory(paths.ReturnRoot);
        File.WriteAllText(
            paths.ReturnEnvelopePath,
            JsonSerializer.Serialize(envelope, JsonOptions) + "\n",
            Utf8NoBom);
        return envelope;
    }

    private static Dictionary<string, string> BuildBaseEntries(
        MockBrokerSessionInput input,
        string returnId,
        string proof)
    {
        var events = new[]
        {
            BuildEvent(input, returnId, 1, "broker.started", "本地 Mock Broker 已启动。"),
            BuildEvent(input, returnId, 2, "broker.sandbox.ready", "固定隔离沙盒已准备。"),
            BuildEvent(input, returnId, 3, "provider.returned", "Mock Provider 已生成固定文本变更。"),
            BuildEvent(input, returnId, 4, "broker.return.submitted", "Broker 已准备提交有界 Return。"),
        };
        var eventText   = string.Join('\n', events.Select(SerializeCompact)) + "\n";
        var proofDigest = Sha256(proof);
        return new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["session_events.ndjson"] = eventText,
            ["summary.md"] = "# Mock Broker Return\n\n仅生成固定证明文本。\n",
            ["changed_files.json"] = SerializeFile(new SortedDictionary<string, object?>
            {
                ["files"] = new[]
                {
                    new SortedDictionary<string, object?>
                    {
                        ["change_type"] = "added",
                        ["path"]        = "docs/mock-provider-proof.txt",
                        ["sha256"]      = proofDigest,
                    },
                },
                ["schema_version"] = SchemaVersion,
            }),
            ["test_report.json"] = SerializeFile(new SortedDictionary<string, object?>
            {
                ["schema_version"] = SchemaVersion,
                ["tests"] = new[]
                {
                    new SortedDictionary<string, object?>
                    {
                        ["command_id"] = "project-tests",
                        ["status"]     = "not_run",
                    },
                },
            }),
            ["build_report.json"] = SerializeFile(new SortedDictionary<string, object?>
            {
                ["schema_version"] = SchemaVersion,
                ["status"]         = "not_run",
            }),
            ["security_report.json"] = SerializeFile(new SortedDictionary<string, object?>
            {
                ["checks"]         = SecurityChecks,
                ["schema_version"] = SchemaVersion,
            }),
            ["questions.md"] = "# Questions\n\nNone.\n",
            ["changes/docs/mock-provider-proof.txt"] = proof,
        };
    }

    private static SortedDictionary<string, object?> BuildEvent(
        MockBrokerSessionInput input,
        string returnId,
        int sequence,
        string eventType,
        string summary) =>
        new(StringComparer.Ordinal)
        {
            ["event_id"]       = $"{returnId}-{sequence:000}",
            ["event_type"]     = eventType,
            ["handoff_id"]     = input.HandoffId,
            ["payload"]        = new SortedDictionary<string, object?>
            {
                ["summary"] = summary,
            },
            ["payload_version"] = SchemaVersion,
            ["provider"]        = Provider,
            ["return_id"]       = returnId,
            ["sequence"]        = sequence,
            ["session_id"]      = input.SessionId,
        };

    private static string ComputeContentManifestDigest(
        IReadOnlyDictionary<string, string> entries)
    {
        var files = entries
            .Where(pair => pair.Key is not "return_manifest.json"
                and not "signatures/manifest.sha256")
            .OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => new SortedDictionary<string, object?>
            {
                ["path"]   = pair.Key,
                ["sha256"] = Sha256(pair.Value),
            })
            .ToArray();
        return Sha256(SerializeCompact(new SortedDictionary<string, object?>
        {
            ["files"] = files,
        }));
    }

    private static string BuildSignature(IReadOnlyDictionary<string, string> entries) =>
        string.Concat(entries
            .Where(pair => pair.Key != "signatures/manifest.sha256")
            .OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => $"{Sha256(pair.Value)}  {pair.Key}\n"));

    private static string ComputeSandboxDigest(BrokerSandboxPaths paths, string proof)
    {
        var facts = new SortedDictionary<string, object?>
        {
            ["docs_readme_sha256"] = Sha256(File.ReadAllText(
                Path.Combine(paths.WorkspaceRoot, "docs", "README.md"),
                Utf8NoBom)),
            ["project_sha256"] = Sha256(File.ReadAllText(
                Path.Combine(paths.WorkspaceRoot, "project.json"),
                Utf8NoBom)),
            ["proof_sha256"] = Sha256(proof),
        };
        return Sha256(SerializeCompact(facts));
    }

    private static MockBrokerSessionInput ReadSessionInput(string path)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Length <= 0 || info.Length > MaxInputBytes)
        {
            throw new InvalidDataException("Broker Session 输入不存在或越界。 ");
        }
        try
        {
            return JsonSerializer.Deserialize<MockBrokerSessionInput>(
                    File.ReadAllText(path, Utf8NoBom),
                    JsonOptions)
                ?? throw new InvalidDataException("Broker Session 输入为空。 ");
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException("Broker Session 输入不是固定 JSON。", exception);
        }
    }

    private static void ValidateInput(MockBrokerSessionInput input, string sessionId)
    {
        if (!string.Equals(input.SchemaVersion, SchemaVersion, StringComparison.Ordinal)
            || !string.Equals(input.SessionId, sessionId, StringComparison.Ordinal)
            || !Guid.TryParseExact(input.SessionId, "D", out _)
            || !Guid.TryParseExact(input.HandoffId, "D", out _)
            || !IsHexDigest(input.RequestDigest, 64)
            || !IsHexDigest(input.PackageDigest, 64)
            || !(IsHexDigest(input.BaseCommit, 40) || IsHexDigest(input.BaseCommit, 64)))
        {
            throw new InvalidDataException("Broker Session 输入绑定无效。 ");
        }
    }

    private static string ParseSessionId(string[] args)
    {
        if (args.Length != 3
            || !string.Equals(args[0], ChildFlag, StringComparison.Ordinal)
            || !string.Equals(args[1], SessionFlag, StringComparison.Ordinal)
            || !Guid.TryParseExact(args[2], "D", out var sessionId))
        {
            throw new ArgumentException("Mock Broker 子进程参数无效。", nameof(args));
        }
        return sessionId.ToString("D");
    }

    private static string SerializeCompact(object value) =>
        JsonSerializer.Serialize(value, JsonOptions);

    private static string SerializeFile(object value) =>
        SerializeCompact(value) + "\n";

    private static string Sha256(string value) =>
        Convert.ToHexString(SHA256.HashData(Utf8NoBom.GetBytes(value))).ToLowerInvariant();

    private static bool IsHexDigest(string value, int length) =>
        value.Length == length && value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');
}
