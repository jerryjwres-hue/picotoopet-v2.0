using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Services.ProductionReference;

namespace PicotooPet.MediaWorker.SmokeTests;

internal static class DurableReferenceSnapshotTests
{
    public static async Task RunAsync()
    {
        await PrivateCopySurvivesRestartAsync();
        await RejectedAuthorityAndOriginalAsync();
        await ReceiptAndSnapshotTamperingAsync();
        await UnsafePathAndOwnershipAsync();
        await ProcessDeathStagesAsync();
        Console.WriteLine("P0_Q2_DURABLE_REFERENCE_SNAPSHOT=PASS (fake Core/Comfy; no GPU)");
    }

    private static async Task RejectedAuthorityAndOriginalAsync()
    {
        foreach (var alter in new Func<ProductionReferenceAssetV11Record, ProductionReferenceAssetV11Record>[]
        {
            r => r with { ProductionJobId = "other" }, r => r with { ProductionTaskId = "other" },
            r => r with { ShotId = "other" }, r => r with { CreativePackageDigest = new string('b', 64) },
            r => r with { AssetId = "other" }, r => r with { ApprovalId = "other" },
            r => r with { RightsScope = "other" }, r => r with { Sha256 = new string('b', 64) },
            r => r with { Bytes = r.Bytes + 1 }, r => r with { ApprovalRequestDigest = new string('f', 64) },
            r => r with { CreativeJobId = "other" }, r => r with { SourceDigest = new string('f', 64) },
        })
        {
            using var f = new Fixture();
            var task = f.Task with { ReferenceAsset = alter(f.Reference) };
            var plan = f.Plan with { Tasks = [task] };
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(plan, task); });
        }
        using (var f = new Fixture())
        {
            f.Approved = false;
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(); });
        }
        foreach (var remove in new[] { false, true })
        {
            using var f = new Fixture();
            if (remove) File.Delete(f.Full(f.Reference.InputRelativePath));
            else File.WriteAllText(f.Full(f.Reference.InputRelativePath), "changed original");
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(); });
        }
        using (var f = new Fixture())
        {
            await DeniedAsync(async () =>
            {
                using var denied = await f.Store().PrepareAsync(f.Plan, f.Task, new string('f', 64),
                    new string('e', 64), f.Journal, CancellationToken.None);
            });
        }
    }

    private static async Task ReceiptAndSnapshotTamperingAsync()
    {
        foreach (var targetReceipt in new[] { false, true })
        foreach (var remove in new[] { false, true })
        {
            using var f = new Fixture();
            string relative;
            using (var lease = await f.PrepareAsync()) relative = lease.RelativePath;
            f.Journal.Save(new("job", "task", f.Digest, new string('e', 64), "Submitting", null));
            var target = f.Full(relative) + (targetReceipt ? ".snapshot.json" : "");
            RemoveDenial(new FileInfo(target));
            if (remove) File.Delete(target); else File.WriteAllText(target, "tampered");
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(); });
            RecoveryTests.Assert(f.Journal.Pending().Single().Phase == "Submitting",
                "tamper cannot erase unknown GPU intent or create replacement bytes");
        }
    }

    private static async Task UnsafePathAndOwnershipAsync()
    {
        foreach (var name in new[] { "../pet.png", "pet.png:stream", "pet.png.", "pet.png ", "/pet.png", "pet\\other.png" })
        {
            using var f = new Fixture();
            var r = f.Reference with { InputRelativePath = $"PicotooPet/references/{f.Reference.Sha256}/{name}" };
            var task = f.Task with { ReferenceAsset = r, TrustedInputAssetRef = r.InputRelativePath };
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(f.Plan with { Tasks = [task] }, task); });
        }
        using (var f = new Fixture())
        {
            var relative = ProductionReferenceSnapshotStore.RelativePathFor(f.Task, f.Digest);
            File.WriteAllBytes(f.Full(relative), f.Bytes); // no ownership receipt: never adopt an unrelated file
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(); });
            RecoveryTests.Assert(File.ReadAllBytes(f.Full(relative)).SequenceEqual(f.Bytes), "foreign input must not be overwritten");
        }
        using (var f = new Fixture())
        {
            var original = f.Full(f.Reference.InputRelativePath);
            var outside = Path.Combine(f.Root, "outside.png");
            File.Move(original, outside);
            File.CreateSymbolicLink(original, outside);
            await DeniedAsync(async () => { using var denied = await f.PrepareAsync(); });
        }
        using (var f = new Fixture())
        {
            string relative;
            using (var lease = await f.PrepareAsync()) relative = lease.RelativePath;
            var directory = Path.GetDirectoryName(f.Full(relative))!;
            await DeniedAsync(() => { Directory.Move(directory, directory + "-renamed"); return Task.CompletedTask; });
        }
    }

    public static async Task ProbeAsync(string root, int stopAt)
    {
        using var f = new Fixture(root);
        f.ApprovalProbe = async count =>
        {
            if (count != stopAt) return;
            Console.WriteLine("I2V_CRASH_STAGE_READY");
            await Task.Delay(Timeout.InfiniteTimeSpan);
        };
        using var lease = await f.PrepareAsync();
        Console.WriteLine("I2V_CRASH_STAGE_READY");
        await Task.Delay(Timeout.InfiniteTimeSpan);
    }

    private static async Task ProcessDeathStagesAsync()
    {
        // 2: verified original/no publication; 3: durable receipt/no snapshot;
        // 6: snapshot published/before ACL; 0: protected snapshot/all pins live.
        foreach (var stopAt in new[] { 2, 3, 6, 0 })
        {
            using var f = new Fixture();
            using var child = Process.Start(new ProcessStartInfo("dotnet")
            {
                UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true,
                ArgumentList = { Assembly.GetExecutingAssembly().Location,
                    "--i2v-snapshot-crash-probe", f.Root, stopAt.ToString(System.Globalization.CultureInfo.InvariantCulture) },
            }) ?? throw new InvalidOperationException("snapshot child did not start");
            try
            {
                var ready = await child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(20));
                RecoveryTests.Assert(ready == "I2V_CRASH_STAGE_READY", "child must reach actual requested snapshot stage");
            }
            finally
            {
                if (!child.HasExited) child.Kill(entireProcessTree: true);
                await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(10));
            }
            using var resumed = await f.PrepareAsync();
            RecoveryTests.Assert(File.ReadAllBytes(f.Full(resumed.RelativePath)).SequenceEqual(f.Bytes),
                "process death must recover exact private bytes without new authority");
            var directory = Path.GetDirectoryName(f.Full(resumed.RelativePath))!;
            resumed.Dispose();
            await DeniedAsync(() => { Directory.Move(directory, directory + "-replaced"); return Task.CompletedTask; });
        }
    }

    internal static void RemoveDenial(FileSystemInfo info)
    {
        var acl = info is DirectoryInfo directory ? (FileSystemSecurity)directory.GetAccessControl() : ((FileInfo)info).GetAccessControl();
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, false, typeof(SecurityIdentifier)))
            if (rule.AccessControlType == AccessControlType.Deny) acl.RemoveAccessRuleSpecific(rule);
        if (info is DirectoryInfo d) d.SetAccessControl((DirectorySecurity)acl);
        else ((FileInfo)info).SetAccessControl((FileSecurity)acl);
    }

    private static async Task PrivateCopySurvivesRestartAsync()
    {
        using var f = new Fixture();
        string path;
        using (var lease = await f.PrepareAsync())
        {
            path = lease.RelativePath;
            RecoveryTests.Assert(path != f.Reference.InputRelativePath,
                "executor must own a private copy, never alter UI staging");
            RecoveryTests.Assert(File.ReadAllBytes(f.Full(path)).SequenceEqual(f.Bytes),
                "private LoadImage must contain exact approved bytes");
        }
        // All process-bound verifier pins are gone, as they would be after a crash.
        await DeniedAsync(() => { File.WriteAllText(f.Full(path), "changed"); return Task.CompletedTask; });
        await DeniedAsync(() => { File.Delete(f.Full(path)); return Task.CompletedTask; });
        using var resumed = await f.PrepareAsync();
        RecoveryTests.Assert(resumed.RelativePath == path, "restart must reuse exact immutable copy");
    }

    internal static async Task DeniedAsync(Func<Task> action)
    {
        try { await action(); }
        catch (Exception error) when (error is UnauthorizedAccessException or IOException
            or InvalidDataException or ProductionWorkerException) { return; }
        throw new InvalidOperationException("unsafe reference operation was admitted");
    }

    internal sealed class Fixture : IDisposable
    {
        public string Root { get; }
        public byte[] Bytes { get; } = Convert.FromBase64String(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=");
        public ProductionReferenceAssetV11Record Reference { get; }
        public ProductionTaskPlanRecord Task { get; }
        public ProductionPlanRecord Plan { get; }
        public string Digest { get; }
        public ProductionSubmissionJournal Journal { get; }
        public bool Approved { get; set; } = true;
        public int ApprovalReads { get; private set; }
        public Func<int, Task>? ApprovalProbe { get; set; }
        public Fixture(string? root = null)
        {
            Root = root ?? Path.Combine(Path.GetTempPath(), "p0-q2-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Root);
            var sha = Convert.ToHexString(SHA256.HashData(Bytes)).ToLowerInvariant();
            Reference = new("reference_asset.v1", "asset", "goal", "creative-job", "creative",
                "job", "task", "shot", new string('a', 64),
                $"PicotooPet/references/{sha}/shot.png", sha, Bytes.Length,
                "USER_SUPPLIED", new string('c', 64), "wan22.i2v.production.v1",
                "approval", new string('d', 64));
            Task = new("task", "shot", 1, "IMAGE_TO_VIDEO", "Executable",
                ComfyWorkflowTemplateValidator.I2VWorkflowId, "same pet", "wan22.safe-negative.v1",
                12, 832, 480, 24, 73, 3000, Reference.InputRelativePath, Reference);
            Plan = new("1.1", "production.comfyui.v1", "job", "creative",
                new string('a', 64), "goal-goal", "video.landscape.v1", 3000, [Task]);
            Digest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(
                JsonSerializer.SerializeToNode(Plan)!))).ToLowerInvariant();
            Directory.CreateDirectory(Path.GetDirectoryName(Full(Reference.InputRelativePath))!);
            File.WriteAllBytes(Full(Reference.InputRelativePath), Bytes);
            Journal = new(Path.Combine(Root, "journal"));
        }
        public string Full(string relative) => Path.Combine(Root, relative.Replace('/', Path.DirectorySeparatorChar));
        public ProductionReferenceSnapshotStore Store() => new(Root, (_, _, digest) => new Approvals(this, digest));
        public Task<DurableReferenceSnapshot> PrepareAsync(ProductionPlanRecord? plan = null,
            ProductionTaskPlanRecord? task = null)
        {
            var actual = plan ?? Plan;
            var digest = Convert.ToHexString(SHA256.HashData(CanonicalJson.Serialize(JsonSerializer.SerializeToNode(actual)!))).ToLowerInvariant();
            return Store().PrepareAsync(actual, task ?? Task, digest, new string('e', 64), Journal, CancellationToken.None);
        }

        private sealed class Approvals(Fixture fixture, string expectedDigest) : ITrustedReferenceApprovalSource
        {
            public async Task<bool> IsApprovedAsync(TrustedReferenceDescriptor candidate, CancellationToken ct)
            {
                fixture.ApprovalReads++;
                if (fixture.ApprovalProbe is not null) await fixture.ApprovalProbe(fixture.ApprovalReads);
                var r = fixture.Reference;
                var authority = new ProductionReferenceAuthorizationV11Record(
                    "reference_authorization.v1", "job", "task", fixture.Digest,
                    new(r.ApprovalId, r.ShotId, r.AssetId, r.InputRelativePath, r.Sha256, r.Bytes), r);
                var job = new ProductionJobRecord("job", "creative", r.CreativePackageDigest,
                    "goal-goal", "production.comfyui.v1", fixture.Digest, "Ready",
                    null, null, null, null, "test", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);
                return fixture.Approved
                    && CoreReferenceApprovalSource.Matches(job, fixture.Plan, authority,
                        candidate, "job", "task", expectedDigest);
            }
        }

        public void Dispose()
        {
            // Test-only explicit ACL takeover; production never removes protection or snapshots.
            if (!Directory.Exists(Root)) return;
            if (OperatingSystem.IsWindows())
            {
                foreach (var path in Directory.EnumerateFileSystemEntries(Root, "*", SearchOption.AllDirectories).Prepend(Root))
                {
                    if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) continue;
                    FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
                    RemoveDenial(info);
                    File.SetAttributes(path, File.GetAttributes(path) & ~FileAttributes.ReadOnly);
                }
            }
            Directory.Delete(Root, recursive: true);
        }
    }
}
