using System.Buffers.Binary;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace PicotooPet.Desktop.Core.OwnerReview;

/// <summary>
/// 独立 SSH -W 传输候选的冻结配置。它不是凭据发放或实机验收凭证。
/// 不允许来自 HTTP 请求、Goal、模型输出或未授权 UI 字段的动态替换。
/// </summary>
public sealed record OwnerReviewSshStdioProfile(
    string MacHost,
    string MacUser,
    int SshPort,
    int CorePort,
    string PinnedKnownHostsFile,
    string ExpectedHostKeyFingerprint,
    string PrivateKeyFile);

/// <summary>
/// 不打开本地监听端口的 SSH 标准输入/输出转发规格。
/// 调用方必须另行核实 Mac SSH、密钥、实际连接以及 Core loopback peer。
/// </summary>
public static partial class OwnerReviewSshStdioProfileVerifier
{
    public const string PinnedHostAlias = "picotoopet-owner-review-mac";
    public const string InternalHttpHost = "owner-review-ssh-stdio.invalid";
    public const string TransportStatus = "TRANSPORT_SECURITY=NOT_LIVE_VERIFIED";

    private const int MaxPinnedFileBytes = 4096;

    [GeneratedRegex(@"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$",
        RegexOptions.CultureInvariant)]
    private static partial Regex HostPattern();

    [GeneratedRegex(@"^[a-z_][a-z0-9_-]{0,31}$", RegexOptions.CultureInvariant)]
    private static partial Regex UserPattern();

    /// <summary>纯本地校验；不启动 SSH、不发网络请求、不读取主人 Bearer。</summary>
    public static ProcessStartInfo BuildPinnedCommand(OwnerReviewSshStdioProfile profile)
    {
        ArgumentNullException.ThrowIfNull(profile);
        if (!HostPattern().IsMatch(profile.MacHost)
            || profile.MacHost.Contains("..", StringComparison.Ordinal)
            || !UserPattern().IsMatch(profile.MacUser)
            || profile.SshPort is < 1 or > 65535
            || profile.CorePort is < 1 or > 65535)
        {
            throw Blocked("OWNER_REVIEW_SSH_PROFILE_INVALID");
        }

        RequireRegularAbsoluteFile(profile.PrivateKeyFile);
        RequireRegularAbsoluteFile(profile.PinnedKnownHostsFile);
        RequireExactPinnedHost(profile.PinnedKnownHostsFile, profile.ExpectedHostKeyFingerprint);

        // 唯一允许的可执行文件：Windows 系统 OpenSSH；禁止 PATH/工作目录劫持。
        var windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        if (string.IsNullOrWhiteSpace(windows))
        {
            throw Blocked("OWNER_REVIEW_SSH_EXECUTABLE_UNVERIFIED");
        }
        var ssh = Path.Combine(windows, "System32", "OpenSSH", "ssh.exe");
        if (!File.Exists(ssh) || (File.GetAttributes(ssh) & FileAttributes.ReparsePoint) != 0)
        {
            throw Blocked("OWNER_REVIEW_SSH_EXECUTABLE_UNVERIFIED");
        }

        // 仅使用 ArgumentList，不经 shell、不执行远程命令，不把 Bearer 放进参数。
        var start = new ProcessStartInfo(ssh)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var option in new[]
        {
            "BatchMode=yes",
            "NumberOfPasswordPrompts=0",
            "StrictHostKeyChecking=yes",
            "UpdateHostKeys=no",
            "UserKnownHostsFile=" + profile.PinnedKnownHostsFile,
            "GlobalKnownHostsFile=none",
            "HostKeyAlias=" + PinnedHostAlias,
            "KnownHostsCommand=none",
            "ProxyCommand=none",
            "ProxyJump=none",
            "PreferredAuthentications=publickey",
            "PubkeyAuthentication=yes",
            "PasswordAuthentication=no",
            "KbdInteractiveAuthentication=no",
            "IdentitiesOnly=yes",
            "IdentityFile=" + profile.PrivateKeyFile,
            "ControlMaster=no",
            "PermitLocalCommand=no",
            "CanonicalizeHostname=no",
            "ClearAllForwardings=yes",
            "ExitOnForwardFailure=yes",
            "ConnectTimeout=8",
            "ConnectionAttempts=1",
            "ServerAliveInterval=5",
            "ServerAliveCountMax=2",
            "LogLevel=ERROR",
        })
        {
            start.ArgumentList.Add("-o");
            start.ArgumentList.Add(option);
        }
        start.ArgumentList.Add("-F");
        start.ArgumentList.Add("none");
        start.ArgumentList.Add("-T");
        start.ArgumentList.Add("-p");
        start.ArgumentList.Add(profile.SshPort.ToString(System.Globalization.CultureInfo.InvariantCulture));
        start.ArgumentList.Add("-l");
        start.ArgumentList.Add(profile.MacUser);
        start.ArgumentList.Add("-W");
        start.ArgumentList.Add("127.0.0.1:" + profile.CorePort.ToString(
            System.Globalization.CultureInfo.InvariantCulture));
        start.ArgumentList.Add(profile.MacHost);
        return start;
    }

    private static void RequireRegularAbsoluteFile(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path)
            || !File.Exists(path) || (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
        {
            throw Blocked("OWNER_REVIEW_SSH_PROTECTED_FILE_REQUIRED");
        }
    }

    private static void RequireExactPinnedHost(string file, string expectedFingerprint)
    {
        // 仅接受单独经主人带外核实的 ED25519 host key；ssh-keyscan 本身不构成信任。
        var content = File.ReadAllBytes(file);
        if (content.Length is 0 or > MaxPinnedFileBytes)
        {
            throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
        }
        var lines = Encoding.UTF8.GetString(content).Split(
            ['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (lines.Length != 1)
        {
            throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
        }
        var parts = lines[0].Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 3 || parts[0] != PinnedHostAlias || parts[1] != "ssh-ed25519")
        {
            throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
        }

        try
        {
            // OpenSSH ED25519 blob: uint32(11), "ssh-ed25519", uint32(32), 32-byte public key.
            var blob = Convert.FromBase64String(parts[2]);
            if (blob.Length != 51
                || BinaryPrimitives.ReadInt32BigEndian(blob.AsSpan(0, 4)) != 11
                || Encoding.ASCII.GetString(blob.AsSpan(4, 11)) != "ssh-ed25519"
                || BinaryPrimitives.ReadInt32BigEndian(blob.AsSpan(15, 4)) != 32)
            {
                throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
            }

            if (!expectedFingerprint.StartsWith("SHA256:", StringComparison.Ordinal))
            {
                throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
            }
            var fingerprint = Convert.FromBase64String(
                expectedFingerprint["SHA256:".Length..].PadRight(44, '='));
            if (fingerprint.Length != 32
                || !CryptographicOperations.FixedTimeEquals(
                    fingerprint, SHA256.HashData(blob)))
            {
                throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_MISMATCH");
            }
        }
        catch (FormatException)
        {
            throw Blocked("OWNER_REVIEW_SSH_HOST_KEY_PIN_INVALID");
        }
    }

    private static OwnerReviewException Blocked(string code) =>
        new(OwnerReviewFailureKind.TransportBlocked, 0, code);
}
