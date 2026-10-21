using System.IO;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

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
            Console.WriteLine("P0_THREE_SHOT_GATE_FILE_HOLD_ALLOW_RESTART=PASS");
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
        }
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
