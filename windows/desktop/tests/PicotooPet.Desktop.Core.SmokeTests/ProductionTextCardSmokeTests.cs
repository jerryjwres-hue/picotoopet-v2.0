using System.Diagnostics;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 C006A local-media 合同、固定渲染边界与既有 Production 生命周期顺序。</summary>
internal static class ProductionTextCardSmokeTests
{
    private const string Text = "Save time with gentle airflow.";
    private const string TextDigest = "f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f";

    public static async Task RunAsync()
    {
        DeserializesClosedTextCardContract();
        await RendersDeterministicallyWithFixedFfmpegArgumentsAsync().ConfigureAwait(false);
        await ReservesBeforeRenderingAndCommitsWithoutPromptAsync().ConfigureAwait(false);
    }

    private static void DeserializesClosedTextCardContract()
    {
        var task = JsonSerializer.Deserialize<ProductionTaskPlanRecord>("""
            {
              "production_task_id":"00000000-0000-4000-8000-000000000601",
              "shot_id":"shot-001","order":1,"render_intent":"TEXT_CARD",
              "execution_disposition":"Executable","execution_backend":"local_media",
              "execution_profile_id":"production.local.text-card.v1","workflow_id":null,
              "positive_prompt":"text card","negative_prompt_policy_id":"wan22.safe-negative.v1",
              "seed":1,"width":480,"height":832,"fps":24,"frame_count":73,
              "target_duration_ms":3000,"trusted_input_asset_ref":null,
              "local_media":{"text_digest":"f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f",
                "text_content":"Save time with gentle airflow.",
                "text_profile_id":"production.local.text-card.v1"}
            }
            """) ?? throw new InvalidOperationException("C006A task contract deserialize failed");

        SmokeAssert.Equal("local_media", task.ExecutionBackend, "Windows 丢失 Core backend authority");
        SmokeAssert.Equal("production.local.text-card.v1", task.ExecutionProfileId, "Windows 丢失 profile authority");
        SmokeAssert.True(task.WorkflowId is null, "local-media task 伪造了 workflow");
        SmokeAssert.Equal(TextDigest, task.LocalMedia?.TextDigest, "Windows 丢失 text digest");
    }

    private static async Task RendersDeterministicallyWithFixedFfmpegArgumentsAsync()
    {
        using var first = new TemporaryRoot();
        using var second = new TemporaryRoot();
        var firstRunner = new RecordingRunner();
        var secondRunner = new RecordingRunner();
        var task = TaskPlan();

        var firstResult = await new ProductionLocalMediaRenderer(firstRunner)
            .RenderAsync("job-001", task, first.Path, CancellationToken.None)
            .ConfigureAwait(false);
        var secondResult = await new ProductionLocalMediaRenderer(secondRunner)
            .RenderAsync("job-001", task, second.Path, CancellationToken.None)
            .ConfigureAwait(false);

        SmokeAssert.Equal(firstResult.OutputRelpath, secondResult.OutputRelpath, "相同 task 输出路径不确定");
        SmokeAssert.Equal(firstResult.OutputSha256, secondResult.OutputSha256, "相同 task 输出摘要不确定");
        SmokeAssert.Equal("video/webm", firstResult.MimeType, "TEXT_CARD 输出不是 WebM");
        SmokeAssert.True(File.Exists(firstResult.OutputPath), "TEXT_CARD WebM 未落入受管输出根");
        var startInfo = firstRunner.StartInfo ?? throw new InvalidOperationException("FFmpeg 未执行");
        SmokeAssert.Equal("ffmpeg.exe", startInfo.FileName, "local-media 可替换 FFmpeg executable");
        SmokeAssert.True(!startInfo.UseShellExecute && startInfo.CreateNoWindow, "local-media 使用了 shell");
        var args = startInfo.ArgumentList.ToArray();
        SmokeAssert.True(args.Contains("libvpx-vp9", StringComparer.Ordinal), "TEXT_CARD 未固定 VP9 codec");
        SmokeAssert.True(args.Contains("73", StringComparer.Ordinal), "TEXT_CARD 未绑定 Core frame_count");
        SmokeAssert.True(!args.Any(item => item.Contains(Text, StringComparison.Ordinal)), "原始文本进入 FFmpeg 参数");
        SmokeAssert.True(!args.Any(item => item.Contains("font", StringComparison.OrdinalIgnoreCase)), "FFmpeg 获得字体路径/参数权限");
        SmokeAssert.True(!args.Contains("-filter_complex", StringComparer.Ordinal), "TEXT_CARD 接受 filter graph");
    }

    private static async Task ReservesBeforeRenderingAndCommitsWithoutPromptAsync()
    {
        using var root = new TemporaryRoot();
        var events = new List<string>();
        var task = TaskPlan();
        var gateway = new RecordingGateway(task, events);
        var renderer = new RecordingRenderer(root.Path, events);
        await using var comfy = ComfyProductionClient.Create();
        await using var service = new ProductionExecutionService(
            gateway,
            comfy,
            renderer,
            () => root.Path,
            "windows-production-smoke");

        var package = await service.RunAsync("job-001").ConfigureAwait(false);

        SmokeAssert.Equal("package-001", package.ProductionPackageId, "existing Production package not returned");
        SmokeAssert.True(
            events.SequenceEqual(["plan", "claim", "attempt", "render", "commit", "package"]),
            $"local-media lifecycle order invalid: {string.Join(',', events)}");
        SmokeAssert.True(gateway.Commit?.ComfyPromptId is null, "local-media commit invented prompt id");
    }

    private static ProductionTaskPlanRecord TaskPlan() => new(
        "00000000-0000-4000-8000-000000000601",
        "shot-001",
        1,
        "TEXT_CARD",
        "Executable",
        null,
        "text card",
        "wan22.safe-negative.v1",
        1,
        480,
        832,
        24,
        73,
        3000,
        null,
        "local_media",
        "production.local.text-card.v1",
        new ProductionLocalMediaPayloadRecord(TextDigest, Text, "production.local.text-card.v1"));

    private sealed class RecordingRunner : IProductionLocalMediaProcessRunner
    {
        public ProcessStartInfo? StartInfo { get; private set; }

        public Task<ProductionLocalMediaProcessResult> RunAsync(
            ProcessStartInfo startInfo,
            TimeSpan timeout,
            CancellationToken cancellationToken)
        {
            StartInfo = startInfo;
            var outputPath = startInfo.ArgumentList[^1];
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(outputPath)!);
            File.WriteAllBytes(outputPath, "deterministic-webm"u8.ToArray());
            return Task.FromResult(new ProductionLocalMediaProcessResult(0, TimedOut: false));
        }
    }

    private sealed class RecordingRenderer(string root, List<string> events) : IProductionLocalMediaRenderer
    {
        public async Task<ProductionLocalMediaArtifact> RenderAsync(
            string productionJobId,
            ProductionTaskPlanRecord task,
            string outputRoot,
            CancellationToken cancellationToken)
        {
            events.Add("render");
            return await new ProductionLocalMediaRenderer(new RecordingRunner())
                .RenderAsync(productionJobId, task, root, cancellationToken)
                .ConfigureAwait(false);
        }
    }

    private sealed class RecordingGateway(ProductionTaskPlanRecord task, List<string> events)
        : IProductionExecutionGateway
    {
        public ProductionTaskCommitRequest? Commit { get; private set; }

        public Task<ProductionPlanRecord> GetProductionPlanAsync(
            string productionJobId,
            CancellationToken cancellationToken)
        {
            events.Add("plan");
            return Task.FromResult(Plan(task));
        }

        public Task<ProductionClaimRecord> ClaimProductionJobAsync(
            string productionJobId,
            string executorId,
            CancellationToken cancellationToken)
        {
            events.Add("claim");
            return Task.FromResult(new ProductionClaimRecord(
                productionJobId,
                executorId,
                "lease-token-000000000000000000000001",
                DateTimeOffset.UtcNow.AddMinutes(2),
                Plan(task),
                []));
        }

        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskAttemptRequest request,
            CancellationToken cancellationToken)
        {
            events.Add("attempt");
            return Task.FromResult(TaskRecord(task, "Running"));
        }

        public Task<ProductionTaskRecord> CommitProductionResultAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskCommitRequest request,
            CancellationToken cancellationToken)
        {
            events.Add("commit");
            Commit = request;
            return Task.FromResult(TaskRecord(task, "Succeeded"));
        }

        public Task<ProductionTaskRecord> FailProductionTaskAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskFailureRequest request,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("failure path not expected");

        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(
            string productionJobId,
            string executorId,
            string leaseToken,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("heartbeat not expected");

        public Task<ProductionPackageRecord?> GetProductionPackageAsync(
            string productionJobId,
            CancellationToken cancellationToken)
        {
            events.Add("package");
            return Task.FromResult<ProductionPackageRecord?>(new ProductionPackageRecord(
                "package-001", productionJobId, "creative-001", new string('a', 64),
                new string('b', 64), "production/package.zip",
                JsonSerializer.SerializeToElement(new { }), "PASS", DateTimeOffset.UtcNow));
        }

        private static ProductionPlanRecord Plan(ProductionTaskPlanRecord task) => new(
            "1.0", "production.comfyui.v1", "job-001", "creative-001", new string('a', 64),
            "pet-dryer-us", "video.vertical.v1", 3000, [task]);

        private static ProductionTaskRecord TaskRecord(ProductionTaskPlanRecord task, string status) => new(
            task.ProductionTaskId, "job-001", task.ShotId, task.Order, task.RenderIntent,
            task.ExecutionDisposition, task.WorkflowId, task, status, 1, null, null, null, null,
            null, null, null, null, null, null, null, DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow, null);
    }

    private sealed class TemporaryRoot : IDisposable
    {
        public TemporaryRoot()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                $"picotoopet-text-card-{Guid.NewGuid():N}");
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public void Dispose()
        {
            if (Directory.Exists(Path))
            {
                Directory.Delete(Path, recursive: true);
            }
        }
    }
}
