using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Services;

/// <summary>Review/Adoption/Commit 面板只通过固定 typed gateway 访问 Mac Core。</summary>
public interface IProviderReviewGateway
{
    Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken);

    Task<ProviderReviewRecord> GetReviewAsync(string sessionId, CancellationToken cancellationToken);

    Task<ProviderReviewRecord> AcceptAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken);

    Task<ProviderReviewRecord> RejectAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken);

    Task<ProviderAdoptionCandidateRecord[]> GetCandidatesAsync(CancellationToken cancellationToken);

    Task<ProviderCommitCandidateRecord> PrepareCommitAsync(
        string adoptionCandidateId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        Task.FromException<ProviderCommitCandidateRecord>(
            new InvalidOperationException(
                "该 Review gateway 未配置 Commit Candidate 写入。"));

    Task<ProviderCommitCandidateRecord[]> GetCommitCandidatesAsync(
        CancellationToken cancellationToken) =>
        Task.FromResult(Array.Empty<ProviderCommitCandidateRecord>());
}

/// <summary>把 Review/Adoption/Commit typed client 接入现有配对会话。</summary>
public sealed class ControlCenterProviderReviewGateway(ControlCenterSession session) : IProviderReviewGateway
{
    private readonly ControlCenterSession _session = session ?? throw new ArgumentNullException(nameof(session));

    public Task<ProviderSessionRecord[]> GetSessionsAsync(CancellationToken cancellationToken) =>
        _session.GetProviderSessionsAsync(cancellationToken);

    public Task<ProviderReviewRecord> GetReviewAsync(
        string sessionId,
        CancellationToken cancellationToken) => _session.GetProviderReviewAsync(sessionId, cancellationToken);

    public Task<ProviderReviewRecord> AcceptAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.AcceptProviderReviewAsync(sessionId, idempotencyKey, cancellationToken);

    public Task<ProviderReviewRecord> RejectAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.RejectProviderReviewAsync(sessionId, idempotencyKey, cancellationToken);

    public Task<ProviderAdoptionCandidateRecord[]> GetCandidatesAsync(
        CancellationToken cancellationToken) => _session.GetProviderAdoptionCandidatesAsync(cancellationToken);

    public Task<ProviderCommitCandidateRecord> PrepareCommitAsync(
        string adoptionCandidateId,
        string idempotencyKey,
        CancellationToken cancellationToken) =>
        _session.PrepareProviderCommitAsync(adoptionCandidateId, idempotencyKey, cancellationToken);

    public Task<ProviderCommitCandidateRecord[]> GetCommitCandidatesAsync(
        CancellationToken cancellationToken) => _session.GetProviderCommitCandidatesAsync(cancellationToken);
}
