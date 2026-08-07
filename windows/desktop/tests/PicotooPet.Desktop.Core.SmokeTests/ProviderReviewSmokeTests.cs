using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;
using PicotooPet.Desktop.ViewModels;

namespace PicotooPet.Desktop.Core.SmokeTests;

/// <summary>Phase 10D-B 人工审阅与落地候选的确定性 Windows 行为合同。</summary>
internal static class ProviderReviewSmokeTests
{
    public static async Task RunAsync()
    {
        var gateway = new FakeProviderReviewGateway();
        var viewModel = new ProviderReviewViewModel(gateway);

        await viewModel.LoadAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("reviewable", viewModel.Review!.ReviewStatus, "ready_for_review 应加载只读 Review");
        SmokeAssert.Equal(1, viewModel.Review.Files.Count, "Review 只应展示有界变更文件");
        SmokeAssert.True(viewModel.CanAccept, "reviewable Return 应允许固定接受动作");
        SmokeAssert.True(viewModel.CanReject, "reviewable Return 应允许固定拒绝动作");
        SmokeAssert.True(viewModel.Review.ReviewDiff.Contains("+reviewed change", StringComparison.Ordinal), "只读 diff 未加载");

        await viewModel.AcceptAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("accepted", viewModel.Review!.ReviewStatus, "接受事实未回写");
        SmokeAssert.True(!viewModel.CanAccept, "接受后不得再次接受");
        SmokeAssert.True(!viewModel.CanReject, "接受后不得反转为拒绝");
        SmokeAssert.True(viewModel.SelectedCandidate is not null, "接受后必须出现唯一 Adoption Candidate");
        SmokeAssert.Equal("queued", viewModel.SelectedCandidate!.Status, "候选初始状态必须 queued");

        gateway.AdvanceCandidate("adoption_ready");
        await viewModel.RefreshCandidateAsync(CancellationToken.None).ConfigureAwait(false);
        SmokeAssert.Equal("adoption_ready", viewModel.SelectedCandidate!.Status, "候选状态未刷新");
        SmokeAssert.True(
            viewModel.CandidateSummary.Contains("不是 merge-ready", StringComparison.Ordinal),
            "Windows 必须明确 adoption_ready 不等于 merge-ready");
    }

    private sealed class FakeProviderReviewGateway : IProviderReviewGateway
    {
        private ProviderReviewRecord _review = new(
            "22222222-2222-2222-2222-222222222222",
            "return-review",
            "reviewable",
            new string('a', 64),
            new string('b', 64),
            1,
            16,
            [
                new ProviderReviewFileRecord(
                    "add",
                    "docs/review.txt",
                    16,
                    null,
                    new string('c', 64)),
            ],
            "--- a/docs/review.txt\n+++ b/docs/review.txt\n+reviewed change\n",
            null,
            null);

        private ProviderAdoptionCandidateRecord? _candidate;

        public Task<ProviderReviewRecord> GetReviewAsync(
            string sessionId,
            CancellationToken cancellationToken) => Task.FromResult(_review);

        public Task<ProviderReviewRecord> AcceptAsync(
            string sessionId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            _candidate = new ProviderAdoptionCandidateRecord(
                "33333333-3333-3333-3333-333333333333",
                sessionId,
                "return-review",
                "queued",
                new string('d', 40),
                new string('a', 64),
                1,
                [],
                null,
                DateTimeOffset.UtcNow,
                DateTimeOffset.UtcNow,
                null);
            _review = _review with
            {
                ReviewStatus = "accepted",
                Decision = "accepted",
                CandidateId = _candidate.CandidateId,
            };
            return Task.FromResult(_review);
        }

        public Task<ProviderReviewRecord> RejectAsync(
            string sessionId,
            string idempotencyKey,
            CancellationToken cancellationToken)
        {
            _review = _review with { ReviewStatus = "rejected", Decision = "rejected" };
            return Task.FromResult(_review);
        }

        public Task<ProviderAdoptionCandidateRecord[]> GetCandidatesAsync(
            CancellationToken cancellationToken) =>
            Task.FromResult(_candidate is null ? [] : new[] { _candidate });

        public void AdvanceCandidate(string status)
        {
            _candidate = _candidate! with
            {
                Status = status,
                ValidationChecks = ["base_hashes", "result_hashes", "git_diff_check", "utf8"],
                UpdatedAt = DateTimeOffset.UtcNow,
                FinishedAt = DateTimeOffset.UtcNow,
            };
        }
    }
}
