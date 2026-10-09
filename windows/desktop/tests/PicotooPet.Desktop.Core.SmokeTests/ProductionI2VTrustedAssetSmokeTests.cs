using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>冻结 C006B2C I2V snapshot 重验与 legacy restart compatibility。</summary>
internal static class ProductionI2VTrustedAssetSmokeTests
{
    public static async Task RunAsync()
    {
        await SnapshotIsReverifiedBeforeSafeLoadImageBindingAsync().ConfigureAwait(false);
        await DeterministicSnapshotMismatchFailsClosedAsync().ConfigureAwait(false);
        await DeterministicMismatchConsumesNoSecondAttemptAsync().ConfigureAwait(false);
        await LegacyRelativeInputRemainsRootBoundAsync().ConfigureAwait(false);
    }

    private static async Task SnapshotIsReverifiedBeforeSafeLoadImageBindingAsync()
    {
        using var input = new TemporaryRoot();
        var (task, relative) = WriteTask(input.Path);

        var resolved = await ProductionTrustedInputResolver.ResolveAsync(
            task, input.Path, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(relative, resolved, "I2V 未返回已重验的 managed relative path");

        var prompt = ComfyWorkflowTemplateValidator.Bind(
            ComfyWorkflowTemplateValidator.I2VWorkflowId,
            ComfyWorkflowCatalog.Load(ComfyWorkflowTemplateValidator.I2VWorkflowId),
            task,
            "PicotooPet/production/job/001-shot",
            resolved);
        var loadImage = prompt
            .Select(item => item.Value)
            .OfType<JsonObject>()
            .Single(node => node["class_type"]?.GetValue<string>() == "LoadImage");
        SmokeAssert.Equal(relative, loadImage["inputs"]?["image"]?.GetValue<string>(),
            "LoadImage 未绑定唯一受管相对路径");
        SmokeAssert.True(!Path.IsPathRooted(resolved), "绝对路径进入 I2V workflow");
    }

    private static async Task DeterministicSnapshotMismatchFailsClosedAsync()
    {
        using var input = new TemporaryRoot();
        var (task, _) = WriteTask(input.Path);
        var snapshot = task.TrustedAsset!;
        var mismatches = new[]
        {
            snapshot with { SizeBytes = snapshot.SizeBytes + 1 },
            snapshot with { Sha256 = new string('0', 64) },
            snapshot with { MediaType = "image/jpeg" },
            snapshot with { Width = snapshot.Width + 1 },
            snapshot with { ManagedRelpath = "../escape.png" },
        };
        foreach (var mismatch in mismatches)
        {
            await ExpectThrowsAsync<InvalidDataException>(() =>
                ProductionTrustedInputResolver.ResolveAsync(
                    task with { TrustedAsset = mismatch },
                    input.Path,
                    CancellationToken.None),
                "I2V snapshot mismatch 未在 submit 前拒绝").ConfigureAwait(false);
        }
    }

    private static async Task LegacyRelativeInputRemainsRootBoundAsync()
    {
        using var input = new TemporaryRoot();
        var relative = "legacy/input.png";
        var path = Path.Combine(input.Path, "legacy", "input.png");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, ImageBytes(12, 8));
        var legacy = TaskPlan(null, relative);

        var resolved = await ProductionTrustedInputResolver.ResolveAsync(
            legacy, input.Path, CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal(relative, resolved, "legacy I2V restart relative path changed");

        await ExpectThrowsAsync<InvalidDataException>(() =>
            ProductionTrustedInputResolver.ResolveAsync(
                legacy with { TrustedInputAssetRef = "../escape.png" },
                input.Path,
                CancellationToken.None),
            "legacy traversal 未拒绝").ConfigureAwait(false);
    }

    private static async Task DeterministicMismatchConsumesNoSecondAttemptAsync()
    {
        using var input = new TemporaryRoot();
        using var output = new TemporaryRoot();
        var (task, _) = WriteTask(input.Path);
        task = task with
        {
            TrustedAsset = task.TrustedAsset! with
            {
                SizeBytes = task.TrustedAsset.SizeBytes + 1,
            },
        };
        var gateway = new RecordingFailureGateway(task);
        var handler = new RejectingComfyHandler();
        using var http = new HttpClient(handler)
        {
            BaseAddress = ComfyProductionClient.FixedBaseAddress,
        };
        await using var comfy = new ComfyProductionClient(http);
        await using var service = new ProductionExecutionService(
            gateway,
            comfy,
            new NeverRenderer(),
            () => output.Path,
            () => input.Path,
            "windows-i2v-smoke");
        var plan = Plan(task);
        var claim = new ProductionClaimRecord(
            "job-001",
            "windows-i2v-smoke",
            "lease-token-000000000000000000000001",
            DateTimeOffset.UtcNow.AddMinutes(2),
            plan,
            []);
        var preflight = new ProductionPreflightSnapshot(
            true, "smoke", input.Path, input.Path, output.Path, input.Path, []);
        var execute = typeof(ProductionExecutionService).GetMethod(
            "ExecuteComfyTaskAsync",
            BindingFlags.Instance | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("I2V execution boundary missing");
        var pending = (Task?)execute.Invoke(
            service,
            [claim, task, preflight, CancellationToken.None])
            ?? throw new InvalidOperationException("I2V execution did not return a task");

        await ExpectThrowsAsync<InvalidOperationException>(
            () => pending,
            "I2V deterministic mismatch did not fail the task").ConfigureAwait(false);
        SmokeAssert.Equal(1, gateway.AttemptCount, "I2V mismatch consumed a second attempt");
        SmokeAssert.Equal(1, gateway.FailureCount, "I2V mismatch did not persist bounded failure");
        SmokeAssert.Equal(0, handler.RequestCount, "I2V mismatch reached Comfy submit");
    }

    private static (ProductionTaskPlanRecord Task, string Relative) WriteTask(string root)
    {
        var bytes = ImageBytes(12, 8);
        var sha = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        var relative = $"PicotooPet/assets/v1/{sha[..2]}/{sha}.png";
        var path = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
        var asset = new ProductionTrustedAssetSnapshotRecord(
            "00000000-0000-4000-8000-0000000006c1", "autonomous_goal", "goal-001",
            "windows.comfy-input.v1", relative, sha, bytes.Length, "image/png", 12, 8);
        return (TaskPlan(asset, null), relative);
    }

    private static ProductionTaskPlanRecord TaskPlan(
        ProductionTrustedAssetSnapshotRecord? asset,
        string? legacyRef) => new(
        "00000000-0000-4000-8000-0000000006c2", "shot-001", 1, "IMAGE_TO_VIDEO",
        "Executable", ComfyWorkflowTemplateValidator.I2VWorkflowId, "trusted i2v prompt",
        "wan22.safe-negative.v1", 1, 832, 480, 24, 73, 3000, legacyRef, "comfy",
        ComfyWorkflowTemplateValidator.I2VWorkflowId, null, asset);

    private static ProductionPlanRecord Plan(ProductionTaskPlanRecord task) => new(
        "1.0", "production.comfyui.v1", "job-001", "creative-001", new string('a', 64),
        "autonomous-goal:goal-001", "video.vertical.v1", 3000, [task]);

    private static byte[] ImageBytes(int width, int height)
    {
        var pixels = Enumerable.Repeat((byte)127, width * height * 4).ToArray();
        var bitmap = BitmapSource.Create(
            width, height, 96, 96, PixelFormats.Bgra32, null, pixels, width * 4);
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var stream = new MemoryStream();
        encoder.Save(stream);
        return stream.ToArray();
    }

    private static async Task ExpectThrowsAsync<TException>(Func<Task> action, string message)
        where TException : Exception
    {
        try
        {
            await action().ConfigureAwait(false);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException(message);
    }

    private sealed class TemporaryRoot : IDisposable
    {
        public TemporaryRoot()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                "picotoopet-i2v-asset-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public void Dispose() => Directory.Delete(Path, recursive: true);
    }

    private sealed class NeverRenderer : IProductionLocalMediaRenderer
    {
        public Task<ProductionLocalMediaArtifact> RenderAsync(
            string productionJobId,
            ProductionTaskPlanRecord task,
            string outputRoot,
            string? trustedInputRoot,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("local renderer must not run for I2V");
    }

    private sealed class RejectingComfyHandler : HttpMessageHandler
    {
        public int RequestCount { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            RequestCount++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.InternalServerError));
        }
    }

    private sealed class RecordingFailureGateway(ProductionTaskPlanRecord task)
        : IProductionExecutionGateway
    {
        public int AttemptCount { get; private set; }
        public int FailureCount { get; private set; }

        public Task<ProductionTaskRecord> MarkProductionAttemptAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskAttemptRequest request,
            CancellationToken cancellationToken)
        {
            AttemptCount++;
            return Task.FromResult(TaskRecord("Running"));
        }

        public Task<ProductionTaskRecord> FailProductionTaskAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskFailureRequest request,
            CancellationToken cancellationToken)
        {
            FailureCount++;
            SmokeAssert.Equal(
                "COMFY_TRUSTED_INPUT_INVALID",
                request.FailureCode,
                "I2V mismatch failure code drifted");
            return Task.FromResult(TaskRecord("Failed"));
        }

        public Task<ProductionPlanRecord> GetProductionPlanAsync(
            string productionJobId,
            CancellationToken cancellationToken) => Task.FromResult(Plan(task));

        public Task<ProductionClaimRecord> ClaimProductionJobAsync(
            string productionJobId,
            string executorId,
            CancellationToken cancellationToken) => throw Unexpected();

        public Task<ProductionJobRecord> HeartbeatProductionJobAsync(
            string productionJobId,
            string executorId,
            string leaseToken,
            CancellationToken cancellationToken) => throw Unexpected();

        public Task<ProductionTaskRecord> CommitProductionResultAsync(
            string productionJobId,
            string productionTaskId,
            ProductionTaskCommitRequest request,
            CancellationToken cancellationToken) => throw Unexpected();

        public Task<ProductionPackageRecord?> GetProductionPackageAsync(
            string productionJobId,
            CancellationToken cancellationToken) => throw Unexpected();

        private ProductionTaskRecord TaskRecord(string status) => new(
            task.ProductionTaskId, "job-001", task.ShotId, task.Order, task.RenderIntent,
            task.ExecutionDisposition, task.WorkflowId, task, status, AttemptCount, null,
            null, null, null, null, null, null, null, null, null, null,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow, null);

        private static InvalidOperationException Unexpected() =>
            new("unexpected gateway call in I2V mismatch smoke");
    }
}
