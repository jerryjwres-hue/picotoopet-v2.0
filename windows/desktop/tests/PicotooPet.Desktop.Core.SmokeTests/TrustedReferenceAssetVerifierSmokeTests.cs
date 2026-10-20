using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Synthetic bytes only; no approval service, Comfy POST, image-quality or GPU claim.</summary>
internal static class TrustedReferenceAssetVerifierSmokeTests
{
    public static async Task RunAsync()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("WINDOWS_NATIVE_GATE_REQUIRED");
        using var fixture = new Fixture();
        await fixture.AcceptAndRevalidateAsync().ConfigureAwait(false);
        await fixture.RejectForgeryAsync().ConfigureAwait(false);
        await fixture.RejectBadFilesAsync().ConfigureAwait(false);
        await fixture.RetainSnapshotAsync().ConfigureAwait(false);
        await fixture.RejectJunctionAsync().ConfigureAwait(false);
        Console.WriteLine("P0_TRUSTED_REFERENCE_VERIFIER=PASS; SYNTHETIC_BYTES_ONLY; GPU=NOT_USED; CORE_INTEGRATION=BLOCKED");
    }

    private sealed class Fixture : IDisposable
    {
        private const string AbcSha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
        private readonly string _workspace = Path.Combine(Path.GetTempPath(), "p0-reference-test-" + Guid.NewGuid().ToString("N"));
        private readonly ApprovalSource _approval = new();
        private readonly TrustedReferenceFilePolicy _policy = new(
            ProductionLocalEnvironment.ResolveUnderRoot,
            ProductionLocalEnvironment.AssertNoLinkEscape,
            ProductionLocalEnvironment.IsOrdinaryFile,
            ProductionLocalEnvironment.Sha256FileAsync);

        private string Root => Path.Combine(_workspace, "input");
        private string Image => Path.Combine(Root, "approved", "reference.png");
        private static TrustedReferenceDescriptor Approved => new("core-approval-1", "shot-1", "asset-1", "approved/reference.png", AbcSha, 3);

        public Fixture()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Image)!);
            File.WriteAllText(Image, "abc");
            _approval.Exact = Approved;
        }

        private TrustedReferenceAssetVerifier Verifier() => new(Root, _policy, _approval);

        public async Task AcceptAndRevalidateAsync()
        {
            using (var lease = await Verifier().VerifyAsync(Approved, "shot-1", "asset-1").ConfigureAwait(false))
            {
                Assert(lease.FullPath == Image, "verified exact managed file");
                Assert(lease.RelativePath == "approved/reference.png", "Comfy gets only the bounded relative path");
            }
            // A new verifier has no cached acceptance; the original Core identity is unchanged.
            using (await Verifier().VerifyAsync(Approved, "shot-1", "asset-1").ConfigureAwait(false)) { }
            File.WriteAllText(Image, "abd");
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "restart must rehash changed bytes").ConfigureAwait(false);
            File.WriteAllText(Image, "abc");
            _approval.Exact = null;
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "restart must reacquire authorization").ConfigureAwait(false);
            _approval.Exact = Approved;
        }

        public async Task RejectForgeryAsync()
        {
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-2", "asset-1"), "wrong requested shot").ConfigureAwait(false);
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-2"), "wrong requested asset").ConfigureAwait(false);
            foreach (var descriptor in new[]
            {
                Approved with { ApprovalId = "forged" }, Approved with { ShotId = "shot-2" },
                Approved with { AssetId = "asset-2" }, Approved with { ByteLength = 4 },
                Approved with { Sha256 = new string('a', 64) }, Approved with { RelativePath = "other.png" },
            })
                await RejectAsync(() => Verifier().VerifyAsync(descriptor, "shot-1", "asset-1"), "descriptor must exactly bind Core approval").ConfigureAwait(false);
            _approval.Exact = null;
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "local existence is not authorization").ConfigureAwait(false);
            _approval.ThrowUnavailable = true;
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "Core unavailable is not authorized").ConfigureAwait(false);
            _approval.ThrowUnavailable = false;
            _approval.Exact = Approved;
            foreach (var descriptor in new[]
            {
                Approved with { ApprovalId = "" }, Approved with { ShotId = "" },
                Approved with { AssetId = "" }, Approved with { Sha256 = "not-a-file-sha" },
                Approved with { Sha256 = AbcSha.ToUpperInvariant() }, Approved with { ByteLength = 0 },
            })
            {
                _approval.Exact = descriptor;
                await RejectAsync(() => Verifier().VerifyAsync(descriptor, descriptor.ShotId, descriptor.AssetId), "malformed descriptor rejected even if authority mistakenly accepts").ConfigureAwait(false);
            }
            _approval.Exact = Approved;
        }

        public async Task RejectBadFilesAsync()
        {
            foreach (var relative in new[] { "../outside.png", "approved/../approved/reference.png", Image, "C:reference.png", "approved/reference.png:stream", "approved/reference.png.", "approved\\..\\approved/reference.png" })
            {
                var descriptor = Approved with { RelativePath = relative };
                _approval.Exact = descriptor; // even an approved descriptor cannot weaken filesystem policy
                await RejectAsync(() => Verifier().VerifyAsync(descriptor, "shot-1", "asset-1"), "unsafe path rejected").ConfigureAwait(false);
            }
            _approval.Exact = Approved;
            File.Delete(Image);
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "missing file").ConfigureAwait(false);
            Directory.CreateDirectory(Image);
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "directory is not an image file").ConfigureAwait(false);
            Directory.Delete(Image);
            foreach (var content in new[] { "", "ab", "abcd", "abd" })
            {
                File.WriteAllText(Image, content);
                await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "empty, length or hash mismatch").ConfigureAwait(false);
            }
            File.Delete(Image);
            File.WriteAllText(Image, "xyz");
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "replacement path must be rehashed").ConfigureAwait(false);
            File.WriteAllText(Image, "abc");
            using var cancelled = new CancellationTokenSource();
            cancelled.Cancel();
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1", cancelled.Token), "cancelled verifier cannot grant lease").ConfigureAwait(false);
        }

        public async Task RetainSnapshotAsync()
        {
            using (await Verifier().VerifyAsync(Approved, "shot-1", "asset-1").ConfigureAwait(false))
            {
                ExpectSharingDenied(() => File.WriteAllText(Image, "abd"));
                ExpectSharingDenied(() => File.Delete(Image));
                ExpectSharingDenied(() => Directory.Move(Path.GetDirectoryName(Image)!, Path.Combine(Root, "swapped")));
                // LoadImage may open the same exact bytes for reading while our lease stays alive.
                Assert(File.ReadAllText(Image) == "abc", "consumer reads approved bytes");
            }
            File.WriteAllText(Image, "abd"); // disposal actually releases locks
            await RejectAsync(() => Verifier().VerifyAsync(Approved, "shot-1", "asset-1"), "released lease cannot authorize replacement").ConfigureAwait(false);
            File.WriteAllText(Image, "abc");

            // Deterministic swap at the policy/hash boundary: verifier must pin BEFORE hashing.
            var attempted = false;
            var racingPolicy = _policy with { Sha256FileAsync = async (path, token) =>
            {
                attempted = true;
                ExpectSharingDenied(() => File.WriteAllText(path, "abd"));
                return await ProductionLocalEnvironment.Sha256FileAsync(path, token).ConfigureAwait(false);
            } };
            using (await new TrustedReferenceAssetVerifier(Root, racingPolicy, _approval).VerifyAsync(Approved, "shot-1", "asset-1").ConfigureAwait(false))
                Assert(attempted, "race probe executed during real verification");

            var revokedDuringHash = _policy with { Sha256FileAsync = async (path, token) =>
            {
                _approval.Exact = null;
                return await ProductionLocalEnvironment.Sha256FileAsync(path, token).ConfigureAwait(false);
            } };
            await RejectAsync(() => new TrustedReferenceAssetVerifier(Root, revokedDuringHash, _approval)
                .VerifyAsync(Approved, "shot-1", "asset-1"), "revocation during verification cannot yield a lease").ConfigureAwait(false);
            _approval.Exact = Approved;
            File.WriteAllText(Image, "abc"); // failed verification must release every resource
        }

        public async Task RejectJunctionAsync()
        {
            var outside = Path.Combine(_workspace, "outside");
            Directory.CreateDirectory(outside);
            File.WriteAllText(Path.Combine(outside, "reference.png"), "abc");
            var junction = Path.Combine(Root, "junction");
            // Junction creation on hosted Windows requires neither Developer Mode nor elevation.
            using var process = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("cmd.exe")
            {
                Arguments = $"/d /c mklink /J \"{junction}\" \"{outside}\"",
                UseShellExecute = false, CreateNoWindow = true,
            }) ?? throw new InvalidOperationException("junction probe could not start");
            await process.WaitForExitAsync().ConfigureAwait(false);
            Assert(process.ExitCode == 0, "junction probe must not silently skip");
            try
            {
                var linked = Approved with { RelativePath = "junction/reference.png" };
                _approval.Exact = linked;
                await RejectAsync(() => Verifier().VerifyAsync(linked, "shot-1", "asset-1"), "junction rejected despite matching bytes and approval").ConfigureAwait(false);
            }
            finally { Directory.Delete(junction); _approval.Exact = Approved; }
        }

        public void Dispose() => Directory.Delete(_workspace, recursive: true);
    }

    // Only the absent external approval authority is doubled; real Desktop policy and real NTFS files are used.
    private sealed class ApprovalSource : ITrustedReferenceApprovalSource
    {
        public TrustedReferenceDescriptor? Exact { get; set; }
        public bool ThrowUnavailable { get; set; }
        public Task<bool> IsApprovedAsync(TrustedReferenceDescriptor descriptor, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (ThrowUnavailable) throw new IOException("synthetic Core offline");
            return Task.FromResult(descriptor == Exact);
        }
    }

    private static async Task RejectAsync(Func<Task<VerifiedReferenceAsset>> action, string message)
    {
        try { using var unexpected = await action().ConfigureAwait(false); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or OperationCanceledException or ArgumentException) { return; }
        throw new InvalidOperationException("Expected fail-closed rejection: " + message);
    }

    private static void ExpectSharingDenied(Action action)
    {
        try { action(); }
        catch (IOException) { return; }
        catch (UnauthorizedAccessException) { return; }
        throw new InvalidOperationException("Approved file/directory changed while verification lease was live");
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
