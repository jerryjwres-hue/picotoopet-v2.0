using System.IO;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services.ProductionReference;
using System.Text.Json;

namespace PicotooPet.MediaWorker.SmokeTests;

/// <summary>真实 Windows 文件共享语义，纯离线 HOLD/ALLOW/重启门禁回归。</summary>
internal static class ThreeShotAcceptanceGateTests
{
    private const string JobId = "eaad8d1e-4f83-48bd-88f5-3a1d7fa6b352";
    private static readonly string Digest = new('a', 64);

    public static void Run()
    {
        var root = Path.Combine(Path.GetTempPath(), "p0-three-shot-gate-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var path = Path.Combine(root, "three-shot-acceptance.json");
        try
        {
            // ── 未曾创建配置时沿用旧无人值守行为，且不能隐式 armed。 ──
            using (var unattended = P0ThreeShotAcceptanceGate.AcquireSubmissionPermitAtPath(JobId, Digest, path))
                RecoveryTests.Assert(unattended is null, "missing never-armed config must remain unattended");
            RecoveryTests.Assert(!File.Exists(path + ".armed"), "missing default cannot create marker");

            // ── HOLD 和非法配置不允许 Core claim/Comfy POST 的任何许可。 ──
            File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}");
            AssertHeld(path, JobId, Digest);
            RecoveryTests.Assert(File.Exists(path + ".armed"), "first observation must persist armed marker");
            File.WriteAllText(path, "{invalid-json");
            AssertHeld(path, JobId, Digest);
            File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"allow\",\"production_job_id\":\"wrong\",\"plan_digest\":\"bad\"}");
            AssertHeld(path, JobId, Digest);

            // ── 精确匹配指定 Job + SHA-256 才能 ALLOW；其它 Job/digest 均 HOLD。 ──
            File.WriteAllText(path, Allow(JobId, Digest));
            AssertHeld(path, Guid.NewGuid().ToString("D"), Digest);
            AssertHeld(path, JobId, new string('b', 64));
            using (var allowed = P0ThreeShotAcceptanceGate.AcquireSubmissionPermitAtPath(JobId, Digest, path))
            {
                RecoveryTests.Assert(allowed is not null, "exact ALLOW must acquire read-only permit");
                // ── Permit 存续期间拒绝配置原地覆盖，覆盖 claim 或 POST 临界区。 ──
                var writeDenied = false;
                try { File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}"); }
                catch (IOException) { writeDenied = true; }
                catch (UnauthorizedAccessException) { writeDenied = true; }
                RecoveryTests.Assert(writeDenied, "active permit must prevent HOLD replacement on Windows");
            }

            // ── 配置删除后的持久标记模拟 Worker 进程完全重启，仍拒绝新 POST。 ──
            File.Delete(path);
            AssertHeld(path, JobId, Digest);
            File.WriteAllText(path, Allow(JobId, Digest));
            using (var resumed = P0ThreeShotAcceptanceGate.AcquireSubmissionPermitAtPath(JobId, Digest, path))
                RecoveryTests.Assert(resumed is not null, "explicit restored ALLOW may resume same job");
            File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}");
            AssertHeld(path, JobId, Digest);
            VerifyLtxBatch(path);
            VerifyStoryBatchLifecycle(Path.Combine(root, "lifecycle-acceptance.json"));
            Console.WriteLine("P0_THREE_SHOT_GATE_FILE_HOLD_ALLOW_RESTART=PASS");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
    }

    private static void VerifyLtxBatch(string path)
    {
        // 01. Use real Windows file semantics, but entirely synthetic jobs.
        var ids = new[] { JobId, "41dd22a4-b738-4931-9c62-55a2a4789690",
            "10000000-0000-4000-8000-000000000003" };
        var digests = new[] { Digest, new string('b', 64), new string('c', 64) };
        var entries = ids.Zip(digests, (id, sha) => new { production_job_id = id, plan_digest = sha }).ToArray();
        var identity = ProductionSubmissionJournal.Hash(string.Join("\n", ids.Zip(digests, (id, sha) => id + ":" + sha)));
        File.WriteAllText(path, JsonSerializer.Serialize(new { schema_version = "1.1", mode = "allow_ltx_batch", jobs = entries }));
        // 02. No legacy Wan permit can consume an LTX batch authorization.
        AssertHeld(path, ids[0], digests[0]);
        for (var i = 0; i < 3; i++)
            using (var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(ids[i], digests[i], identity, path))
                RecoveryTests.Assert(permit is not null, "exact batch member must acquire LTX permit");
        void Reject(string id, string sha, string? batch)
        {
            try
            {
                using var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(id, sha, batch, path);
                throw new InvalidOperationException("LTX batch unexpectedly allowed");
            }
            catch (ProductionWorkerException error) when (error.Code == "P0_THREE_SHOT_ACCEPTANCE_HELD") { }
        }
        Reject(ids[0], digests[0], null);
        Reject(ids[0], digests[1], identity);
        Reject(ids[0], digests[0], new string('f', 64));
        File.WriteAllText(path, JsonSerializer.Serialize(new { schema_version = "1.1", mode = "allow_ltx_batch", jobs = entries.Reverse() }));
        Reject(ids[0], digests[0], identity);
        File.WriteAllText(path, JsonSerializer.Serialize(new { schema_version = "1.1", mode = "allow_ltx_batch", jobs = new[] { entries[0], entries[0], entries[2] } }));
        Reject(ids[0], digests[0], identity);

        // 03. The next-shot policy never skips an unresolved predecessor.
        var now = DateTimeOffset.UtcNow;
        var jobs = ids.Select((id, i) => new ProductionJobRecord(id, "creative", Digest, "project",
            "production.ltx.desktop.local.v1", digests[i], "NeedsHuman", null, null,
            "LTX_SIGNED_WORKER_NOT_ENABLED", null, "fixture-" + i, now, now, now)).ToArray();
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.NextLtxBatchJob(jobs) == jobs[0], "shot one must run first");
        var settled = jobs[0] with { FailureCode = "LTX_PILOT_REVIEW_REQUIRED" };
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.NextLtxBatchJob([settled, jobs[1], jobs[2]]) == jobs[1],
            "only technical candidate settlement may advance");
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.NextLtxBatchJob([jobs[0] with { Status = "Rendering" }, jobs[1], jobs[2]]) is null,
            "unresolved predecessor must hold batch");
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.NextLtxBatchJob([jobs[0], jobs[1] with { FailureCode = "LTX_PILOT_REVIEW_REQUIRED" }, jobs[2]]) is null,
            "out-of-order settlement must hold batch");
        // 04. Exercise the actual desktop writer from an explicit HOLD;
        //     an existing unrelated allow cannot be replaced by this action.
        File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}");
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(jobs, path);
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(jobs, path); // exact retry
        using (var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(ids[0], digests[0], identity, path))
        {
            var blocked = false;
            try { P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(jobs, path); }
            catch (IOException) { blocked = true; }
            RecoveryTests.Assert(blocked, "active GPU permit must prevent writer access");
        }
        try
        {
            P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath([jobs[0]], path);
            throw new InvalidOperationException("different ALLOW overwritten");
        }
        catch (ProductionWorkerException error) when (error.Code == "LTX_OPERATOR_HOLD_REQUIRED") { }
        // 05. Replacement permits preserve the two settled neighbors and
        //     allow exactly one new held shot, even at position two.
        var settledJobs = jobs.Select(job => job with { FailureCode = "LTX_PILOT_REVIEW_REQUIRED" }).ToArray();
        var rerollId = "10000000-0000-4000-8000-000000000004";
        var variant = "10000000-0000-4000-8000-000000000005";
        var replacement = jobs[1] with { ProductionJobId = rerollId, PlanDigest = new string('d', 64),
            IdempotencyKey = $"reviewed-ltx-reroll-v12-{ids[1]}-{variant}" };
        P0ThreeShotAcceptanceGate.ReplaceSettledLtxShotAtPath(settledJobs, 1, replacement, path);
        var changed = new[] { settledJobs[0], replacement, settledJobs[2] };
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.NextLtxBatchJob(changed) == replacement,
            "single reroll should not regenerate settled neighbors");
        var changedIdentity = ProductionSubmissionJournal.Hash(string.Join("\n", changed.Select(job =>
            job.ProductionJobId + ":" + job.PlanDigest)));
        using (var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(
            rerollId, replacement.PlanDigest!, changedIdentity, path))
            RecoveryTests.Assert(permit is not null, "only replaced exact job gets the new permit");
        Reject(ids[1], digests[1], changedIdentity);
        Reject(rerollId, replacement.PlanDigest!, identity);
        File.Delete(path);
        Reject(ids[0], digests[0], identity);
        Console.WriteLine("LTX_ORDERED_BATCH_GATE=PASS; GPU_POST=0");
    }

    // P0-A: consecutive stories. A finished batch returns to HOLD in code, so
    // story B / C never require a hand-edited acceptance file. HOLD only
    // removes permission; in-flight or unfinished batches are never closed.
    private static void VerifyStoryBatchLifecycle(string path)
    {
        var now = DateTimeOffset.UtcNow;
        ProductionJobRecord[] Story(char seed) => Enumerable.Range(1, 3).Select(i => new ProductionJobRecord(
            $"{seed}0000000-0000-4000-8000-00000000000{i}", "creative-" + seed, Digest, "project-" + seed,
            "production.ltx.desktop.local.v1", new string((char)('0' + i), 63) + seed, "NeedsHuman", null, null,
            "LTX_SIGNED_WORKER_NOT_ENABLED", null, $"fixture-{seed}-{i}", now, now, null)).ToArray();
        ProductionJobRecord[] Settled(ProductionJobRecord[] jobs) =>
            jobs.Select(job => job with { FailureCode = "LTX_PILOT_REVIEW_REQUIRED", FinishedAt = now }).ToArray();
        string Mode() => JsonElement.Parse(File.ReadAllText(path)).GetProperty("mode").GetString()!;
        void Expect(string code, Action action, string message)
        {
            try { action(); throw new InvalidOperationException(message); }
            catch (ProductionWorkerException error) when (error.Code == code) { }
        }

        var a = Story('a'); var b = Story('b'); var c = Story('c');
        RecoveryTests.Assert(a.All(LtxProductionExecutor.IsSelected) && Settled(a).All(LtxProductionExecutor.IsCandidateSettled),
            "lifecycle fixtures must use the real executor predicates");
        File.WriteAllText(path, "{\"schema_version\":\"1.0\",\"mode\":\"hold\"}");
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(a, path);

        // 01. Old behaviour (the reported blocker) is still enforced for an
        //     UNFINISHED previous batch: no silent overwrite of a live permit.
        Expect("LTX_OPERATOR_HOLD_REQUIRED", () => P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(b, path),
            "unfinished story A must not be replaced by B");
        Expect("LTX_BATCH_NOT_FINISHED", () => P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(a, false, path),
            "unfinished story A must not be closed implicitly");
        Expect("LTX_BATCH_IN_FLIGHT", () => P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(
            [a[0] with { Status = "Rendering" }, a[1], a[2]], true, path), "rendering batch must never be closed");
        Expect("LTX_BATCH_IN_FLIGHT", () => P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(
            [a[0] with { LeaseExecutorId = "worker" }, a[1], a[2]], true, path), "leased batch must never be closed");
        Expect("LTX_BATCH_CHANGED", () => P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(Settled(b), false, path),
            "a different batch's facts cannot close the active permit");
        RecoveryTests.Assert(Mode() == "allow_ltx_batch", "rejected closes must leave the permit untouched");

        // 02. Story A finished -> HOLD -> story B armed, with no file editing.
        P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(Settled(a), false, path);
        RecoveryTests.Assert(Mode() == "hold", "finished story A must return to HOLD");
        P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(Settled(a), false, path); // idempotent
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(b, path);
        var identityB = ProductionSubmissionJournal.Hash(string.Join("\n", b.Select(job => job.ProductionJobId + ":" + job.PlanDigest)));
        using (var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(b[0].ProductionJobId, b[0].PlanDigest!, identityB, path))
            RecoveryTests.Assert(permit is not null, "story B must be admitted after A returned to HOLD");
        var identityA = ProductionSubmissionJournal.Hash(string.Join("\n", a.Select(job => job.ProductionJobId + ":" + job.PlanDigest)));
        Expect("P0_THREE_SHOT_ACCEPTANCE_HELD", () =>
        {
            using var stale = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(a[0].ProductionJobId, a[0].PlanDigest!, identityA, path);
        }, "closed story A must never regain a permit");

        // 03. An explicit abandon may close an unfinished, idle story B
        //     (never-run shots and a failed shot), then story C proceeds.
        P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath([Settled(b)[0], b[1] with { Status = "Failed", FailureCode = "LTX_RENDER_FAILED" }, b[2]], true, path);
        RecoveryTests.Assert(Mode() == "hold", "explicit abandon must return idle story B to HOLD");
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath(c, path);
        RecoveryTests.Assert(Mode() == "allow_ltx_batch", "story C must be armed after B was abandoned");

        // 04. An active GPU permit blocks the HOLD writer, like every writer.
        var settledC = Settled(c);
        var identityC = ProductionSubmissionJournal.Hash(string.Join("\n", c.Select(job => job.ProductionJobId + ":" + job.PlanDigest)));
        using (var permit = P0ThreeShotAcceptanceGate.AcquireLtxSubmissionPermitAtPath(c[2].ProductionJobId, c[2].PlanDigest!, identityC, path))
        {
            var blocked = false;
            try { P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(settledC, false, path); }
            catch (IOException) { blocked = true; }
            RecoveryTests.Assert(blocked, "active GPU permit must prevent the HOLD writer");
        }
        P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath(settledC, false, path);
        RecoveryTests.Assert(Mode() == "hold", "story C returns to HOLD once finished");

        // 05. Single-shot ALLOW (schema 1.0) follows the same lifecycle.
        P0ThreeShotAcceptanceGate.ArmReviewedLtxJobsAtPath([a[0]], path);
        P0ThreeShotAcceptanceGate.ReturnLtxBatchToHoldAtPath([Settled(a)[0]], false, path);
        RecoveryTests.Assert(Mode() == "hold", "finished single-shot pilot returns to HOLD");
        // 06. FLUX first frames for another story close a finished permit; the
        //     same story's permit is kept so its own rerolls are not revoked.
        RecoveryTests.Assert(P0ThreeShotAcceptanceGate.BelongsToStory(a, "creative-a")
            && !P0ThreeShotAcceptanceGate.BelongsToStory(a, "creative-b")
            && !P0ThreeShotAcceptanceGate.BelongsToStory([a[0], b[1]], "creative-a")
            && !P0ThreeShotAcceptanceGate.BelongsToStory([], "creative-a"),
            "FLUX story boundary must match the creative package exactly");

        // 07. FLUX paths come only from the SHA-pinned runner's own constants.
        var runnerSource = "COMFY = Path(r\"D:\\x\\ComfyUI\")\nPY = Path(r\"D:\\x\\python.exe\")\n";
        var (comfy, python) = FluxRunnerLocalPaths.ParseRunnerPaths(runnerSource);
        RecoveryTests.Assert(comfy == @"D:\x\ComfyUI" && python == @"D:\x\python.exe", "runner paths parse");
        foreach (var bad in new[] { "", runnerSource + runnerSource, runnerSource.Replace("D:\\x\\ComfyUI", "ComfyUI") })
            try { FluxRunnerLocalPaths.ParseRunnerPaths(bad); throw new InvalidOperationException("ambiguous runner paths accepted"); }
            catch (InvalidDataException error) when (error.Message == "FLUX_DRAFT_RUNNER_PATHS_INVALID") { }
        Console.WriteLine("LTX_STORY_BATCH_LIFECYCLE_A_B_C=PASS; FLUX_RUNNER_PATHS=PASS; GPU_POST=0");
    }

    private static string Allow(string jobId, string digest) =>
        "{\"schema_version\":\"1.0\",\"mode\":\"allow\",\"production_job_id\":\"" +
        jobId + "\",\"plan_digest\":\"" + digest + "\"}";

    private static void AssertHeld(string path, string jobId, string digest)
    {
        try
        {
            using var permit = P0ThreeShotAcceptanceGate.AcquireSubmissionPermitAtPath(jobId, digest, path);
            throw new InvalidOperationException("HOLD unexpectedly returned a permit");
        }
        catch (ProductionWorkerException ex) when (ex.Code == "P0_THREE_SHOT_ACCEPTANCE_HELD")
        {
            // ── 仅接受正式 fail-closed code，不把任意运行错误算作通过。 ──
        }
    }
}
