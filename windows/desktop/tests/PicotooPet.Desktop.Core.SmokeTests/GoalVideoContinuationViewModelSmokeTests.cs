using System.Reflection;
using System.Text.Json;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>验证 Windows 只保留 Core continuation 投影，不发明成功或保存原始返回。</summary>
internal static class GoalVideoContinuationViewModelSmokeTests
{
    public static async Task RunAsync()
    {
        var gateway = new FixtureGateway();
        var viewModel = new GoalVideoContinuationViewModel(gateway);
        viewModel.SetContext(Goal(), Handoff(ready: false));
        SmokeAssert.True(!viewModel.CanSubmit, "未就绪交接不得启用返回提交");

        viewModel.SetContext(Goal(), Handoff(ready: true));
        gateway.GetError = new ApiException("NOT_FOUND", "missing", false, "trace", 404);
        await viewModel.RefreshAsync().ConfigureAwait(false);
        SmokeAssert.True(viewModel.Continuation is null, "GET 404 不得伪造 continuation");
        SmokeAssert.Equal("尚未提交 Web GPT 返回", viewModel.StatusText, "GET 404 状态文案错误");

        gateway.GetError = null;
        gateway.PostResult = Continuation("production-job-1");
        gateway.GetResult = gateway.PostResult;
        const string secret = "TOP_SECRET_RAW_RETURN";
        var payload = GoalVideoReturnParser.Parse($"{{\"creative_summary\":\"{secret}\"}}");
        await viewModel.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.Equal("production-job-1", viewModel.Continuation?.ProductionJobId, "提交后未保存 Core 投影");
        SmokeAssert.True(
            !InstanceStrings(viewModel).Any(value => value.Contains(secret, StringComparison.Ordinal)),
            "ViewModel 持久保存了原始 GPT 返回");

        gateway.PostResult = Continuation("production-job-post-accepted");
        gateway.GetError = new ApiException("INVALID_RESPONSE", "raw invalid body", false, "trace", 502);
        await viewModel.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.Equal(
            "production-job-post-accepted",
            viewModel.Continuation?.ProductionJobId,
            "POST 已接受时，后续 GET 异常不应清空服务端投影");
        SmokeAssert.True(
            !viewModel.StatusText.Contains("raw invalid body", StringComparison.Ordinal),
            "GET 异常正文泄露到 UI");
        gateway.GetError = null;
        gateway.PostResult = Continuation("production-job-1");

        gateway.PostError = new ApiException("NETWORK_TIMEOUT", "raw timeout", true, "trace", 0);
        gateway.GetError = new ApiException("NETWORK_ERROR", "raw reconcile failure", true, "trace", 0);
        await viewModel.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.Equal(
            "production-job-post-accepted",
            viewModel.Continuation?.ProductionJobId,
            "不明确 POST 对账失败清空了既有 Core 投影");
        SmokeAssert.True(viewModel.ErrorMessage.Contains("重试", StringComparison.Ordinal), "对账失败未给出安全重试提示");
        gateway.GetError = null;

        gateway.PostError = new ApiException(
            "AUTONOMOUS_VIDEO_RETURN_CONFLICT",
            "raw conflict body",
            false,
            "trace",
            409);
        await viewModel.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.Equal(
            "production-job-post-accepted",
            viewModel.Continuation?.ProductionJobId,
            "409 冲突错误清空了已接受的 Core 投影");
        SmokeAssert.True(
            viewModel.ErrorMessage.Contains("冲突", StringComparison.Ordinal)
            && !viewModel.ErrorMessage.Contains("raw conflict body", StringComparison.Ordinal),
            "409 未映射为安全非重试消息");
        gateway.PostError = null;

        var restarted = new GoalVideoContinuationViewModel(gateway);
        restarted.SetContext(Goal(), Handoff(ready: true));
        await restarted.RefreshAsync().ConfigureAwait(false);
        SmokeAssert.Equal("production-job-1", restarted.Continuation?.ProductionJobId, "刷新未从 Core 重建状态");

        var retrying = new FixtureGateway
        {
            PostError = new ApiException("NETWORK_ERROR", "raw network body", true, "trace", 0),
            GetError = new ApiException("NOT_FOUND", "missing", false, "trace", 404),
        };
        var failed = new GoalVideoContinuationViewModel(retrying);
        failed.SetContext(Goal(), Handoff(ready: true));
        await failed.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.True(failed.Continuation is null, "网络失败不得发明成功状态");
        SmokeAssert.True(failed.ErrorMessage.Contains("重试", StringComparison.Ordinal), "网络失败未给出安全重试提示");
        SmokeAssert.True(!failed.ErrorMessage.Contains("raw network body", StringComparison.Ordinal), "UI 泄露原始异常正文");

        var reconciled = new FixtureGateway
        {
            PostError = new ApiException("NETWORK_TIMEOUT", "ambiguous", true, "trace", 0),
            GetResult = Continuation("production-job-reconciled"),
        };
        var ambiguous = new GoalVideoContinuationViewModel(reconciled);
        ambiguous.SetContext(Goal(), Handoff(ready: true));
        await ambiguous.SubmitAsync(payload).ConfigureAwait(false);
        SmokeAssert.Equal(
            "production-job-reconciled",
            ambiguous.Continuation?.ProductionJobId,
            "不明确 POST 未通过 GET 对账");


        var staleGateway = new FixtureGateway
        {
            PendingGet = new TaskCompletionSource<GoalVideoContinuationRecord>(
                TaskCreationOptions.RunContinuationsAsynchronously),
        };
        var switching = new GoalVideoContinuationViewModel(staleGateway);
        switching.SetContext(Goal("goal-old"), Handoff(ready: true, goalId: "goal-old"));
        var staleRefresh = switching.RefreshAsync();
        switching.SetContext(Goal("goal-new"), Handoff(ready: true, goalId: "goal-new"));
        staleGateway.PendingGet.SetResult(Continuation("production-old", "goal-old"));
        await staleRefresh.ConfigureAwait(false);
        SmokeAssert.True(
            switching.Continuation is null,
            "旧 Goal 的延迟刷新覆盖了新 Goal continuation");
    }

    private static IEnumerable<string> InstanceStrings(object instance) =>
        instance.GetType()
            .GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
            .Select(field => field.GetValue(instance))
            .OfType<string>();

    private static HumanGoalRecord Goal(string goalId = "goal-1") => new(
        goalId, null, "workflow-1", "human", "product.research_to_video", "P1",
        "研究产品并生成视频", JsonDocument.Parse("{}").RootElement.Clone(), "local-first",
        false, null, "Completed", "goal-key", DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);

    private static GoalHandoffMetadataRecord Handoff(bool ready, string goalId = "goal-1") => new(
        "1.0", goalId, ready, $"{goalId}.zip", new string('a', 64), 100,
        "web-gpt-master-v1.0", true);

    private static GoalVideoContinuationRecord Continuation(
        string productionJobId,
        string goalId = "goal-1") => new(
        goalId, new string('a', 64), new string('b', 64), "creative-job",
        "11111111-1111-4111-8111-111111111111", new string('c', 64),
        "creative_ready", productionJobId, "Ready");

    private sealed class FixtureGateway : IGoalVideoContinuationGateway
    {
        public GoalVideoContinuationRecord? PostResult { get; set; }
        public GoalVideoContinuationRecord? GetResult { get; set; }
        public ApiException? PostError { get; set; }
        public ApiException? GetError { get; set; }
        public TaskCompletionSource<GoalVideoContinuationRecord>? PendingGet { get; set; }

        public Task<GoalVideoContinuationRecord> SubmitGoalVideoReturnAsync(
            string goalId,
            JsonElement payload,
            CancellationToken cancellationToken)
        {
            if (PostError is not null)
            {
                throw PostError;
            }
            return Task.FromResult(PostResult ?? Continuation("production-job"));
        }

        public Task<GoalVideoContinuationRecord> GetGoalVideoContinuationAsync(
            string goalId,
            CancellationToken cancellationToken)
        {
            if (GetError is not null)
            {
                throw GetError;
            }
            if (PendingGet is not null)
            {
                return PendingGet.Task;
            }
            return Task.FromResult(GetResult ?? Continuation("production-job", goalId));
        }
    }
}
