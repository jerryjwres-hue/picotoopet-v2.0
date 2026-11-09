using System.Diagnostics;
using System.IO;
using System.Text.Json;
using PicotooPet.Desktop.Core.OwnerReview;

namespace PicotooPet.OwnerReview.SmokeTests;

/// <summary>
/// Synthetic, offline tests for the production Owner Review wiring. No SSH session, no real key,
/// host, credential or Core is touched; production activation stays locked.
/// </summary>
internal static class LiveWiringTests
{
    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static string Code(Func<OwnerReviewLiveResult> open, out OwnerReviewClient? client)
    {
        var result = open();
        client = result.Client;
        return result.LockCode;
    }

    /// <summary>A protected directory with the fixed file names the wiring expects.</summary>
    private static string LiveDirectory(SshStdioFactoryTests.Fixture fixture, Action<Dictionary<string, object>>? mutate = null)
    {
        var root = Path.Combine(Path.GetTempPath(), "owner-review-live-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        SshStdioFactoryTests.ProtectDirectory(root);
        File.Copy(fixture.Identity, Path.Combine(root, OwnerReviewLiveWiring.PrivateKeyFileName));
        File.Copy(fixture.KnownHosts, Path.Combine(root, OwnerReviewLiveWiring.KnownHostsFileName));
        var document = new Dictionary<string, object>
        {
            ["schema_version"] = "owner_review_live_profile.v1",
            ["mac_host"] = "synthetic-mac.example.invalid",
            ["mac_user"] = "owner",
            ["ssh_port"] = 22,
            ["core_port"] = 8765,
            ["expected_host_key_fingerprint"] = fixture.Fingerprint,
        };
        mutate?.Invoke(document);
        File.WriteAllText(Path.Combine(root, OwnerReviewLiveWiring.ProfileFileName), JsonSerializer.Serialize(document));
        return root;
    }

    public static Task LockedByDefaultAsync()
    {
        Check(!OwnerReviewTransportGate.PinnedSshStdioActivated, "SSH stdio activation gate must stay false");
        Check(!OwnerReviewTransportGate.EncryptedMacTransportAccepted, "legacy encrypted gate must stay false");

        var store = new SshStdioFactoryTests.CountingStore();
        var missingDirectory = Path.Combine(Path.GetTempPath(), "owner-review-never-created-" + Guid.NewGuid().ToString("N"));
        var processesBefore = Process.GetProcessesByName("ssh").Length;

        // Production entry: the first lock closes before any file, credential or process is touched.
        var production = OwnerReviewLiveWiring.TryOpen(store);
        Check(!production.IsOpen && production.Client is null, "production wiring must be locked");
        Check(production.LockCode == "OWNER_REVIEW_SSH_STDIO_NOT_ACTIVATED", "locked for the gate: " + production.LockCode);
        var internalLocked = OwnerReviewLiveWiring.TryOpen(null, missingDirectory, store);
        Check(internalLocked.LockCode == "OWNER_REVIEW_SSH_STDIO_NOT_ACTIVATED", "null token never reaches the disk");
        Check(!Directory.Exists(missingDirectory), "locked path must not create anything");
        Check(store.Reads == 0, "locked wiring must not read the owner credential");
        Check(Process.GetProcessesByName("ssh").Length == processesBefore, "locked wiring must not start ssh");
        return Task.CompletedTask;
    }

    public static Task ProfileGateAsync()
    {
        using var fixture = new SshStdioFactoryTests.Fixture();
        var token = OwnerReviewSshStdioActivation.ForSyntheticTest();
        var store = new SshStdioFactoryTests.CountingStore();
        var created = new List<string>();
        try
        {
            string Make(Action<Dictionary<string, object>>? mutate = null)
            {
                var dir = LiveDirectory(fixture, mutate);
                created.Add(dir);
                return dir;
            }

            // Missing profile.
            var empty = Path.Combine(Path.GetTempPath(), "owner-review-live-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(empty);
            SshStdioFactoryTests.ProtectDirectory(empty);
            created.Add(empty);
            Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, empty, store), out _) == OwnerReviewLiveWiring.ProfileMissingCode, "missing profile");
            Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, "relative\\dir", store), out _) == OwnerReviewLiveWiring.ProfileInvalidCode, "relative directory");

            // Profile content that is not exactly the strict schema.
            foreach (var (label, mutate) in new (string, Action<Dictionary<string, object>>)[]
            {
                ("unknown field", d => d["identity_file"] = "C:\\elsewhere\\key"),
                ("wrong schema", d => d["schema_version"] = "owner_review_live_profile.v2"),
                ("blank host", d => d["mac_host"] = " "),
                ("blank fingerprint", d => d["expected_host_key_fingerprint"] = ""),
            })
            {
                var dir = Make(mutate);
                Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, dir, store), out var c) == OwnerReviewLiveWiring.ProfileInvalidCode && c is null, label);
            }

            // Out-of-range ports and a wrong fingerprint are refused by the typed profile verifier.
            var badPort = Make(d => d["core_port"] = 70000);
            Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, badPort, store), out _) == "OWNER_REVIEW_SSH_PROFILE_INVALID", "bad port");
            var wrongPin = Make(d => d["expected_host_key_fingerprint"] = "SHA256:" + new string('A', 43));
            Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, wrongPin, store), out _) == "OWNER_REVIEW_SSH_HOST_KEY_PIN_MISMATCH", "wrong host key pin");

            // A profile any other principal could rewrite could redirect the owner credential.
            var open = Make();
            SshStdioFactoryTests.GrantEveryoneRead(Path.Combine(open, OwnerReviewLiveWiring.ProfileFileName), directory: false);
            Check(Code(() => OwnerReviewLiveWiring.TryOpen(token, open, store), out _) == OwnerReviewProtectedFileAclCodes.TooBroad, "over-broad profile ACL");

            // Good profile + token: the typed pinned client, no process, no credential read.
            var good = Make();
            var before = Process.GetProcessesByName("ssh").Length;
            var result = OwnerReviewLiveWiring.TryOpen(token, good, store);
            try
            {
                Check(result.IsOpen && result.LockCode.Length == 0, "valid synthetic profile opens the typed client");
                Check(store.Reads == 0, "opening reads no owner credential");
                Check(Process.GetProcessesByName("ssh").Length == before, "opening starts no ssh process");
            }
            finally
            {
                result.Client?.Dispose();
            }
        }
        finally
        {
            foreach (var dir in created)
            {
                try { Directory.Delete(dir, recursive: true); } catch (IOException) { }
            }
        }
        return Task.CompletedTask;
    }
}
