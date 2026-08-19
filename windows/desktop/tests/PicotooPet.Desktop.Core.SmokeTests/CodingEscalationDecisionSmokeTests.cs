using System.Globalization;
using System.Net;
using System.Text;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;
using PicotooPet.Desktop.Views.Pages;

namespace PicotooPet.Desktop.Core.SmokeTests;

internal static class CodingEscalationDecisionSmokeTests
{
    public static async Task RunAsync()
    {
        VerifyGatewayIsReadOnly();
        VerifyPanelHasNoProviderOverrideControls();
        await VerifyFixedGetRouteAsync().ConfigureAwait(false);
        await VerifyStableFormattingAsync().ConfigureAwait(false);
    }

    private static void VerifyGatewayIsReadOnly()
    {
        var methods = typeof(ICodingEscalationDecisionGateway).GetMethods();
        Assert(methods.Length == 1, "Frugal Windows gateway 必须只有一个只读方法");
        Assert(methods[0].Name == "GetDecisionAsync", "Frugal Windows gateway 只能读取决策");
    }

    private static async Task VerifyFixedGetRouteAsync()
    {
        var handler = new RecordingHandler();
        using var httpClient = new HttpClient(handler);
        await using var client = new MacCoreCodingEscalationClient(
            httpClient,
            new Uri("https://mac-core.example/"),
            "fixture-device-token");

        var record = await client.GetDecisionAsync("goal 42", CancellationToken.None)
            .ConfigureAwait(false);

        Assert(record.GoalId == "goal 42", "Frugal GET 反序列化 goal_id 失败");
        Assert(handler.Method == HttpMethod.Get, "Frugal client 不得使用写方法");
        Assert(
            handler.Path == "/api/v1/coding-escalations/goal%2042/decision",
            "Frugal client 必须只访问固定 decision GET 路由");
    }

    private static async Task VerifyStableFormattingAsync()
    {
        var localGateway = new StubGateway(BuildRecord(
            action: "local_only",
            chosenProvider: "none",
            score: 86,
            lower: 0.81,
            upper: 0.90,
            reasons: ["LOCAL_CONFIDENCE_SUFFICIENT"]));
        var local = new CodingEscalationDecisionViewModel(localGateway)
        {
            GoalId = "goal-local",
        };
        await local.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        Assert(
            local.DecisionSummary.Contains("本地 86 分", StringComparison.Ordinal)
            && local.DecisionSummary.Contains("0.81–0.90", StringComparison.Ordinal)
            && local.DecisionSummary.Contains("未使用外部 Coding AI", StringComparison.Ordinal),
            "本地高置信摘要不稳定");

        var externalGateway = new StubGateway(BuildRecord(
            action: "external_provider",
            chosenProvider: "codex",
            score: 61,
            lower: 0.54,
            upper: 0.67,
            reasons: ["EXTERNAL_PROVIDER_JUSTIFIED"]));
        var external = new CodingEscalationDecisionViewModel(externalGateway)
        {
            GoalId = "goal-codex",
        };
        await external.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        Assert(
            external.DecisionSummary.Contains("选择 Codex", StringComparison.Ordinal)
            && external.DecisionSummary.Contains("Claude Code 未调用", StringComparison.Ordinal),
            "外部 Provider 摘要必须明确只调用一家");
    }

    private static void VerifyPanelHasNoProviderOverrideControls()
    {
        var panel = new CodingEscalationDecisionPanel();
        panel.Measure(new System.Windows.Size(900, 600));
        panel.Arrange(new System.Windows.Rect(0, 0, 900, 600));

        Assert(CountVisual<System.Windows.Controls.ComboBox>(panel) == 0,
            "Frugal 决策卡不得提供 Provider/模型下拉选择");
        Assert(CountVisual<System.Windows.Controls.PasswordBox>(panel) == 0,
            "Frugal 决策卡不得收集凭据");
        Assert(CountVisual<System.Windows.Controls.WebBrowser>(panel) == 0,
            "Frugal 决策卡不得嵌入 Provider 登录页");
    }

    private static CodingEscalationDecisionRecord BuildRecord(
        string action,
        string chosenProvider,
        double score,
        double lower,
        double upper,
        string[] reasons) =>
        new(
            DecisionId: "11111111-1111-1111-1111-111111111111",
            GoalId: chosenProvider == "none" ? "goal-local" : "goal-codex",
            DecisionDigest: new string('a', 64),
            PolicyVersion: "frugal-coding.v1",
            ChosenProvider: chosenProvider,
            Decision: new CodingEscalationDecision(
                PolicyVersion: "frugal-coding.v1",
                GoalId: chosenProvider == "none" ? "goal-local" : "goal-codex",
                TaskClass: "repository_maintenance",
                Eligibility: true,
                Action: action,
                LocalQualityScore: score,
                ConfidenceCenter: score / 100.0,
                ConfidenceLower: lower,
                ConfidenceUpper: upper,
                RiskScore: 0.2,
                ReasonCodes: reasons,
                CandidateProviderScores: [],
                ProviderHistory: [],
                ChosenProvider: chosenProvider,
                ExternalSessionsRemaining: chosenProvider == "none" ? 2 : 1,
                DecisionDigest: new string('a', 64)),
            CreatedAt: DateTimeOffset.Parse(
                "2026-08-19T00:00:00Z",
                CultureInfo.InvariantCulture));

    private static int CountVisual<T>(System.Windows.DependencyObject root)
        where T : System.Windows.DependencyObject
    {
        var count = root is T ? 1 : 0;
        for (var index = 0; index < System.Windows.Media.VisualTreeHelper.GetChildrenCount(root); index++)
        {
            count += CountVisual<T>(System.Windows.Media.VisualTreeHelper.GetChild(root, index));
        }
        return count;
    }

    private sealed class StubGateway : ICodingEscalationDecisionGateway
    {
        private readonly CodingEscalationDecisionRecord _record;

        public StubGateway(CodingEscalationDecisionRecord record) => _record = record;

        public Task<CodingEscalationDecisionRecord> GetDecisionAsync(
            string goalId,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert(goalId == _record.GoalId, "ViewModel 必须按 Goal ID 读取 Frugal 决策");
            return Task.FromResult(_record);
        }
    }

    private sealed class RecordingHandler : HttpMessageHandler
    {
        public HttpMethod? Method { get; private set; }
        public string? Path { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Method = request.Method;
            Path = request.RequestUri?.AbsolutePath;
            const string payload = """
                {
                  "decision_id":"11111111-1111-1111-1111-111111111111",
                  "goal_id":"goal 42",
                  "decision_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                  "policy_version":"frugal-coding.v1",
                  "chosen_provider":"none",
                  "decision":{
                    "policy_version":"frugal-coding.v1",
                    "goal_id":"goal 42",
                    "task_class":"repository_maintenance",
                    "eligibility":true,
                    "action":"local_only",
                    "local_quality_score":86.0,
                    "confidence_center":0.86,
                    "confidence_lower":0.81,
                    "confidence_upper":0.90,
                    "risk_score":0.1,
                    "reason_codes":["LOCAL_CONFIDENCE_SUFFICIENT"],
                    "candidate_provider_scores":[],
                    "provider_history":[],
                    "chosen_provider":"none",
                    "external_sessions_remaining":2,
                    "decision_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                  },
                  "created_at":"2026-08-19T00:00:00Z"
                }
                """;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json"),
            });
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
