using System.Security.Principal;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Services;

namespace PicotooPet.MediaWorker;

/// <summary>显式启动的每用户控制台运行时；不安装服务/计划任务，不启动 WPF 或另一个渲染栈。</summary>
internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        try
        {
            if (!OperatingSystem.IsWindows()) return Error("MEDIA_WINDOWS_REQUIRED");
            using var identity = WindowsIdentity.GetCurrent();
            if (identity.IsSystem) return Error("MEDIA_PER_USER_REQUIRED");
            if (args is ["--stop"])
            {
                // User-only named event, no service/Task Scheduler/registry writes.
                using var signal = EventWaitHandle.OpenExisting(StopEventName(identity));
                signal.Set(); return 0;
            }
            if (args is ["--cancel", var jobId])
            {
                await using var client = await ClientAsync(CancellationToken.None).ConfigureAwait(false);
                await client.CancelAsync(jobId).ConfigureAwait(false);
                Console.WriteLine("MEDIA_CORE_CANCEL_REQUESTED"); return 0;
            }
            if (args.Length != 0) return Error("MEDIA_ARGUMENT_INVALID");
            using var stopEvent = new EventWaitHandle(false, EventResetMode.ManualReset, StopEventName(identity));
            using var stop = new CancellationTokenSource();
            Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Cancel(); };
            using var wait = new EventRegistration(stopEvent, stop);
            var journal = new ProductionSubmissionJournal(ProductionSubmissionJournal.DefaultRoot);
            using var reconciler = ComfyPromptReconciler.Create();
            // Refresh credentials and endpoint on every tick: offline/unpaired startup remains recoverable.
            var host = new MediaWorkerHost(journal, new ReconnectingExecutor(), GetJobsAsync, reconciler, WriteStatus);
            await host.RunAsync(stop.Token).ConfigureAwait(false);
            return 0;
        }
        catch (ProductionWorkerException e) { return Error(e.Code); }
        catch (Exception) { return Error("MEDIA_WORKER_UNAVAILABLE"); }
    }
    private static string StopEventName(WindowsIdentity identity) => "Local\\PicotooPet.MediaWorker.Stop." + ProductionSubmissionJournal.Hash(identity.User?.Value ?? identity.Name)[..24];
    private static async Task<MacCoreProductionClient> ClientAsync(CancellationToken ct)
    {
        var settingsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PicotooPetV2", "Desktop", "settings.json");
        var settings = await new DesktopSettingsStore(settingsPath).LoadAsync(ct).ConfigureAwait(false);
        var token = new CredentialManagerTokenStore().Read();
        if (string.IsNullOrWhiteSpace(token)) throw new ProductionWorkerException("MEDIA_PAIRING_REQUIRED");
        return MacCoreProductionClient.Create(MacCoreClientOptions.CreateDefault(new Uri(settings.MacBaseUrl), token));
    }
    private static async Task<ProductionJobRecord[]> GetJobsAsync(CancellationToken ct)
    {
        await using var client = await ClientAsync(ct).ConfigureAwait(false);
        return await client.GetJobsAsync(ct).ConfigureAwait(false);
    }
    private sealed class ReconnectingExecutor : IProductionJobExecutor
    {
        public async Task<ProductionPackageRecord> RunAsync(string jobId, CancellationToken cancellationToken = default)
        {
            await using var client = await ClientAsync(cancellationToken).ConfigureAwait(false);
            await using var comfy = ComfyProductionClient.Create();
            await using var executor = new ProductionExecutionService(new HeadlessProductionGateway(client), comfy);
            return await executor.RunAsync(jobId, cancellationToken).ConfigureAwait(false);
        }
    }
    private static void WriteStatus(string code) => Console.WriteLine(code + " " + (code switch
    {
        "MEDIA_IDLE" => "后台媒体 Worker 已启动，等待 Core 可领取任务。关闭 GUI 不会停止本进程。",
        "MEDIA_PAIRING_REQUIRED" => "请先在现有 Windows 界面完成 Mac 配对。",
        "MEDIA_PREFLIGHT_FAILED" => "已停止：请检查 ComfyUI core nodes，以及 pinned Wan2.2 5B / UMT5 / VAE 模型与哈希；修复后显式重启 Worker。",
        "MEDIA_SUBMISSION_UNKNOWN" or "MEDIA_PENDING_RECONCILIATION" => "已有 GPU 提交尚未对账，已阻止重复渲染；请恢复原 ComfyUI 实例/history。",
        "MEDIA_WAITING_FOR_CORE_LEASE" => "等待现有 Core lease 到期后恢复，不抢占其他 executor。",
        "MEDIA_WORKER_STOPPED" => "后台 Worker 已明确停止；已提交的 ComfyUI 作业保留供重启对账。",
        _ => "Mac API、ComfyUI、模型或工具暂不可用；保留提交身份，稍后重新检查。",
    }));
    private static int Error(string code) { WriteStatus(code); return 1; }
    private sealed class EventRegistration : IDisposable
    {
        private readonly RegisteredWaitHandle _wait;
        public EventRegistration(WaitHandle signal, CancellationTokenSource stop) =>
            _wait = ThreadPool.RegisterWaitForSingleObject(signal, (_, _) => stop.Cancel(), null, Timeout.Infinite, executeOnlyOnce: true);
        public void Dispose() => _wait.Unregister(null);
    }
}
