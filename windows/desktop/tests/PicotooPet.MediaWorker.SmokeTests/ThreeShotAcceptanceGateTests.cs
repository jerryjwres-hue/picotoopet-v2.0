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
        File.Delete(path);
        Reject(ids[0], digests[0], identity);
        Console.WriteLine("LTX_ORDERED_BATCH_GATE=PASS; GPU_POST=0");
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
