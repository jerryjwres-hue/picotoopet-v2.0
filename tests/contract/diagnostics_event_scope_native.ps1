param([Parameter(Mandatory)][string]$RepoRoot)
$ErrorActionPreference = 'Stop'
$source = Get-Content (Join-Path $RepoRoot 'windows/desktop/tools/PicotooPet.Desktop.Diagnostics/Program.cs') -Raw
$start = $source.IndexOf('internal static class DiagnosticTaskScope', [StringComparison]::Ordinal)
$end = $source.IndexOf('/// <summary>Bounded sidecar evidence', [StringComparison]::Ordinal)
if ($start -lt 0 -or $end -le $start) { throw 'DIAGNOSTIC_TASK_SCOPE_MISSING' }
$scope = $source.Substring($start, $end - $start)
$fixture = @'
#nullable enable
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
SCOPE_SOURCE
public static class DiagnosticEventScopeFixture {
    public static async Task Run() {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        var channel = Channel.CreateBounded<JsonElement>(1);
        var probeId = Guid.NewGuid().ToString("N");
        var targetId = Guid.NewGuid().ToString("D");
        // ── Replay exceeds capacity before the task consumer starts; no target is discarded.
        for (var i = 0; i < 2000; i++) {
            using var old = JsonDocument.Parse(JsonSerializer.Serialize(new {
                task_type = "phase2.link.acceptance", resource_tag = "phase2-diagnostic",
                task_id = Guid.NewGuid().ToString("D"), payload = new { diagnostic_run_id = "old-run" }
            }));
            if (DiagnosticTaskScope.BelongsToProbe(old.RootElement, probeId))
                await channel.Writer.WriteAsync(old.RootElement.Clone(), deadline.Token);
        }
        using var target = JsonDocument.Parse(JsonSerializer.Serialize(new {
            task_type = "phase2.link.acceptance", resource_tag = "phase2-diagnostic",
            task_id = targetId, payload = new { diagnostic_run_id = probeId, machine = "中文🐾", created_at = "1900-01-01" }
        }));
        Require(DiagnosticTaskScope.BelongsToProbe(target.RootElement, probeId), "Target lost or server clock incorrectly used");
        await channel.Writer.WriteAsync(target.RootElement.Clone(), deadline.Token);
        var received = await channel.Reader.ReadAsync(deadline.Token);
        Require(received.GetProperty("task_id").GetString() == targetId, "Early task event not preserved");
        foreach (var malformed in new[] { "null", "{}", "{\"task_type\":1}", "{\"task_type\":\"other\"}" }) {
            using var doc = JsonDocument.Parse(malformed);
            Require(!DiagnosticTaskScope.BelongsToProbe(doc.RootElement, probeId), "Unrelated replay accepted");
        }
        Console.WriteLine("DIAGNOSTIC_EVENT_SCOPE=PASS; HISTORICAL_EVENTS=2000; CAPACITY=1; TARGET_DELIVERED=1; CORE_POST=0");
    }
    private static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
}
'@
Add-Type -TypeDefinition $fixture.Replace('SCOPE_SOURCE', $scope)
[DiagnosticEventScopeFixture]::Run().GetAwaiter().GetResult()
