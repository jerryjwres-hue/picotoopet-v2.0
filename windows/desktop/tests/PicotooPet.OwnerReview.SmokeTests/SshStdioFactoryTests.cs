using System.Buffers.Binary;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using PicotooPet.Desktop.Core.OwnerReview;

namespace PicotooPet.OwnerReview.SmokeTests;

/// <summary>
/// Synthetic, offline tests for the typed pinned-SSH-stdio client factory and the NTFS ACL gate.
/// No SSH session is established, no real key/credential/host is touched, no listener is opened.
/// </summary>
internal static class SshStdioFactoryTests
{
    internal sealed class CountingStore : IOwnerReviewCredentialStore
    {
        public int Reads { get; private set; }

        public string? Read()
        {
            Reads++;
            return "synthetic-owner-review-credential-0001";
        }

        public void Save(string credential)
        {
        }

        public void Delete()
        {
        }
    }

    internal sealed class Fixture : IDisposable
    {
        public Fixture()
        {
            Root = Path.Combine(Path.GetTempPath(), "owner-review-ssh-factory-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Root);
            ProtectDirectory(Root);
            KnownHosts = Path.Combine(Root, "approved-known-hosts");
            Identity = Path.Combine(Root, "synthetic-key-not-valid");
            File.WriteAllText(Identity, "not-a-real-private-key");
            var blob = new byte[51];
            BinaryPrimitives.WriteInt32BigEndian(blob.AsSpan(0, 4), 11);
            Encoding.ASCII.GetBytes("ssh-ed25519").CopyTo(blob, 4);
            BinaryPrimitives.WriteInt32BigEndian(blob.AsSpan(15, 4), 32);
            for (var i = 0; i < 32; i++) blob[i + 19] = (byte)(i + 7);
            File.WriteAllText(
                KnownHosts,
                OwnerReviewSshStdioProfileVerifier.PinnedHostAlias
                + " ssh-ed25519 " + Convert.ToBase64String(blob) + Environment.NewLine);
            Fingerprint = "SHA256:" + Convert.ToBase64String(SHA256.HashData(blob)).TrimEnd('=');
            Profile = new OwnerReviewSshStdioProfile(
                "synthetic-mac.example.invalid", "owner", 22, 8765, KnownHosts, Fingerprint, Identity);
        }

        public string Root { get; }
        public string KnownHosts { get; }
        public string Identity { get; }
        public string Fingerprint { get; }
        public OwnerReviewSshStdioProfile Profile { get; }

        public void Dispose() => Directory.Delete(Root, recursive: true);
    }

    /// <summary>Protected DACL: current user, SYSTEM and Administrators only; no inheritance from parent.</summary>
    internal static void ProtectDirectory(string directory)
    {
        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        foreach (var sid in new[]
        {
            WindowsIdentity.GetCurrent().User!,
            new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null),
            new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null),
        })
        {
            security.AddAccessRule(new FileSystemAccessRule(
                sid,
                FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                PropagationFlags.None,
                AccessControlType.Allow));
        }
        new DirectoryInfo(directory).SetAccessControl(security);
    }

    internal static void GrantEveryoneRead(string path, bool directory)
    {
        var everyone = new SecurityIdentifier(WellKnownSidType.WorldSid, null);
        if (directory)
        {
            var info = new DirectoryInfo(path);
            var security = info.GetAccessControl();
            security.AddAccessRule(new FileSystemAccessRule(
                everyone, FileSystemRights.ReadAndExecute, InheritanceFlags.None, PropagationFlags.None,
                AccessControlType.Allow));
            info.SetAccessControl(security);
        }
        else
        {
            var info = new FileInfo(path);
            var security = info.GetAccessControl();
            security.AddAccessRule(new FileSystemAccessRule(
                everyone, FileSystemRights.Read, AccessControlType.Allow));
            info.SetAccessControl(security);
        }
    }

    private static string? CodeOf(Action action)
    {
        try
        {
            action();
            return null;
        }
        catch (OwnerReviewException error)
        {
            return error.Code;
        }
    }

    private static void True(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static OwnerReviewClient Make(
        Uri address, OwnerReviewTransportMode mode, IOwnerReviewCredentialStore store, HttpMessageHandler? handler = null) =>
        new(address, mode, store, handler);

    private static int SshProcesses() => Process.GetProcessesByName("ssh").Length;

    public static Task AclGateAsync()
    {
        using (var good = new Fixture())
        {
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(good.Identity)) is null,
                "protected key + parent directory must pass");
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(good.KnownHosts)) is null,
                "protected known_hosts + parent directory must pass");
        }
        using (var wideKey = new Fixture())
        {
            GrantEveryoneRead(wideKey.Identity, directory: false);
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(wideKey.Identity))
                == OwnerReviewProtectedFileAclCodes.TooBroad,
                "Everyone ACE on the private key must fail closed");
        }
        using (var wideKnownHosts = new Fixture())
        {
            GrantEveryoneRead(wideKnownHosts.KnownHosts, directory: false);
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(wideKnownHosts.KnownHosts))
                == OwnerReviewProtectedFileAclCodes.TooBroad,
                "Everyone ACE on known_hosts must fail closed");
        }
        using (var wideDirectory = new Fixture())
        {
            GrantEveryoneRead(wideDirectory.Root, directory: true);
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(wideDirectory.Identity))
                == OwnerReviewProtectedFileAclCodes.TooBroad,
                "Everyone ACE on the parent directory must fail closed even when the file is tight");
        }
        using (var nullDacl = new Fixture())
        {
            var raw = new RawSecurityDescriptor(ControlFlags.SelfRelative, null, null, null, null);
            var bytes = new byte[raw.BinaryLength];
            raw.GetBinaryForm(bytes, 0);
            var info = new FileInfo(nullDacl.Identity);
            var security = new FileSecurity();
            security.SetSecurityDescriptorBinaryForm(bytes, AccessControlSections.Access);
            info.SetAccessControl(security);
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(nullDacl.Identity))
                == OwnerReviewProtectedFileAclCodes.TooBroad,
                "a null DACL (everyone full control) must fail closed");
        }
        {
            // Distinguish a present zero-ACE (deny-all) DACL from a null (allow-all) DACL.
            // Both fail closed; use a synthetic descriptor so no on-disk ACL is changed.
            var currentUser = WindowsIdentity.GetCurrent().User!;
            var raw = new RawSecurityDescriptor(
                ControlFlags.DiscretionaryAclPresent | ControlFlags.SelfRelative,
                currentUser, currentUser, null, new RawAcl(2, 0));
            var bytes = new byte[raw.BinaryLength];
            raw.GetBinaryForm(bytes, 0);
            var security = new FileSecurity();
            security.SetSecurityDescriptorBinaryForm(
                bytes, AccessControlSections.Owner | AccessControlSections.Access);
            True(CodeOf(() => OwnerReviewProtectedFileAcl.RequireProtected(security, currentUser))
                == OwnerReviewProtectedFileAclCodes.Unverified,
                "a present zero-ACE DACL must fail closed as unusable");
        }
        using (var good = new Fixture())
        {
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require(good.Identity + ".missing"))
                == OwnerReviewProtectedFileAclCodes.Unverified,
                "missing file is unverified, not allowed");
            True(CodeOf(() => OwnerReviewProtectedFileAcl.Require("relative-key"))
                == OwnerReviewProtectedFileAclCodes.Unverified,
                "relative path is unverified, not allowed");
        }
        return Task.CompletedTask;
    }

    public static async Task FactoryAsync()
    {
        // Production stays locked and the legacy gate is untouched.
        True(OwnerReviewSshStdioActivation.TryGetProductionActivation() is null,
            "production activation must be withheld");
        True(!OwnerReviewTransportGate.PinnedSshStdioActivated
            && !OwnerReviewTransportGate.EncryptedMacTransportAccepted,
            "both transport gates stay closed");
        True(CodeOf(() => OwnerReviewTransportGate.Require(
                OwnerReviewTransportMode.VerifiedEncrypted, new Uri("https://example.invalid/")))
            == "OWNER_REVIEW_TRANSPORT_BLOCKED",
            "legacy VerifiedEncrypted stays blocked");

        using var fixture = new Fixture();
        var store = new CountingStore();
        var before = SshProcesses();

        True(CodeOf(() => OwnerReviewClient.CreatePinnedSshStdio(fixture.Profile, store, null))
            == "OWNER_REVIEW_SSH_STDIO_NOT_ACTIVATED",
            "no activation token, no client");

        // Public constructor can never build the SSH mode: no mislabeled handler, no default direct HTTP.
        var synthetic = OwnerReviewSshStdioCandidate.SyntheticAuthority;
        True(Throws<ArgumentException>(() => Make(
                synthetic, OwnerReviewTransportMode.PinnedSshStdio, store)),
            "public ctor must refuse PinnedSshStdio without handler");
        True(Throws<ArgumentException>(() => Make(
                synthetic, OwnerReviewTransportMode.PinnedSshStdio, store, new MockOwnerReviewCore())),
            "public ctor must refuse an injected handler for PinnedSshStdio");

        // Wrong endpoints for the SSH mode.
        foreach (var bad in new[]
        {
            "https://owner-review-ssh-stdio.invalid/", "http://owner-review-ssh-stdio.invalid:8766/",
            "http://192.168.68.70:8766/", "http://127.0.0.1:8766/", "http://owner-review-mock.invalid/",
            "http://user@owner-review-ssh-stdio.invalid/", "http://owner-review-ssh-stdio.invalid/x",
        })
        {
            True(CodeOf(() => OwnerReviewTransportGate.Require(
                    OwnerReviewTransportMode.PinnedSshStdio, new Uri(bad)))
                == "OWNER_REVIEW_TRANSPORT_BLOCKED", "endpoint must be blocked: " + bad);
        }
        True(CodeOf(() => OwnerReviewTransportGate.Require(
                OwnerReviewTransportMode.PinnedSshStdio, synthetic)) is null,
            "fixed synthetic authority is the only accepted endpoint");

        // Wrong / missing pin and lax ACL fail before any process or handler exists.
        True(CodeOf(() => OwnerReviewClient.CreatePinnedSshStdio(
                fixture.Profile with { ExpectedHostKeyFingerprint = "SHA256:" + new string('A', 43) },
                store, OwnerReviewSshStdioActivation.ForSyntheticTest()))
            == "OWNER_REVIEW_SSH_HOST_KEY_PIN_MISMATCH", "wrong pin must fail closed");
        True(CodeOf(() => OwnerReviewClient.CreatePinnedSshStdio(
                fixture.Profile with { PinnedKnownHostsFile = fixture.KnownHosts + ".missing" },
                store, OwnerReviewSshStdioActivation.ForSyntheticTest()))
            == "OWNER_REVIEW_SSH_PROTECTED_FILE_REQUIRED", "missing pin file must fail closed");
        GrantEveryoneRead(fixture.Identity, directory: false);
        True(CodeOf(() => OwnerReviewClient.CreatePinnedSshStdio(
                fixture.Profile, store, OwnerReviewSshStdioActivation.ForSyntheticTest()))
            == OwnerReviewProtectedFileAclCodes.TooBroad, "lax key ACL must block the factory");

        using (var strict = new Fixture())
        {
            var client = OwnerReviewClient.CreatePinnedSshStdio(
                strict.Profile, store, OwnerReviewSshStdioActivation.ForSyntheticTest());
            True(store.Reads == 0, "construction must not read the owner credential");
            True(SshProcesses() == before, "construction must not start ssh");
            client.Dispose();
            client.Dispose();
            var disposed = false;
            try
            {
                await client.GetProposalAsync("goal-synthetic-0001", CancellationToken.None);
            }
            catch (ObjectDisposedException)
            {
                disposed = true;
            }
            True(disposed, "a disposed client must release its handler and refuse use");
            True(SshProcesses() == before, "disposed client must not leave or start ssh");

            // The isolated handler refuses every non-synthetic endpoint: no plaintext/LAN fallback.
            using var handler = OwnerReviewSshStdioCandidate.CreateIsolatedHandler(strict.Profile);
            using var http = new HttpClient(handler, disposeHandler: false);
            foreach (var url in new[] { "http://127.0.0.1:9/", "http://192.168.68.70:8766/",
                "http://owner-review-ssh-stdio.invalid:8080/" })
            {
                try
                {
                    await http.GetAsync(url);
                    throw new InvalidOperationException("handler must not reach " + url);
                }
                catch (HttpRequestException error)
                {
                    True(error.InnerException is OwnerReviewException inner
                        && inner.Code == "OWNER_REVIEW_SSH_ENDPOINT_MISMATCH",
                        "fallback endpoint must be rejected by the connect callback: " + url);
                }
            }
            True(SshProcesses() == before, "rejected endpoints must not start ssh");

            // Duplicate security options are rejected (OpenSSH keeps the first value of a repeat).
            var start = OwnerReviewSshStdioProfileVerifier.BuildPinnedCommand(strict.Profile);
            True(start.ArgumentList.Count(a => a.StartsWith("HostKeyAlias=", StringComparison.Ordinal)) == 1,
                "exactly one HostKeyAlias");
            True(CodeOf(() => OwnerReviewSshStdioProfileVerifier.RequireUniqueOptions(
                    ["-o", "HostKeyAlias=a", "-o", "hostkeyalias=b"]))
                == "OWNER_REVIEW_SSH_DUPLICATE_OPTION", "duplicate -o option must fail closed");
        }
    }

    private static bool Throws<T>(Action action) where T : Exception
    {
        try
        {
            action();
            return false;
        }
        catch (T)
        {
            return true;
        }
    }
}
