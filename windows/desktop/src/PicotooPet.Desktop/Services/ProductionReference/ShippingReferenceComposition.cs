using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// Formal same-EXE composition of paired Core authority and the existing snapshot store.
/// Owner-paired private Windows OS/account + Journal/Comfy is the explicit B trust
/// foundation. DPAPI/Ed25519 and image measurements do not provide remote attestation.
/// Core's local-console enrollment and current HOLD remain independent requirements.
/// </summary>
internal sealed class ShippingReferenceComposition(ControlCenterSession session, string executorId)
{
    private Action? _sessionGuard;
    private Action SessionGuard => _sessionGuard ??= session.CreateProductionSessionGuard();
    public ProductionReferenceSnapshotStore CreateSnapshotStore(string inputRoot) =>
        new(inputRoot, (plan, task, digest) => new CoreWorkerChallengeClient.SessionBoundApproval(new CoreReferenceApprovalSource(
            session, plan.ProductionJobId, task.ProductionTaskId, digest), SessionGuard));

    public void RequireVerifiedWorkerProof(ProductionPlanRecord plan)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(executorId);
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        _ = WorkerLocalPairing.Require(executorId);
        SessionGuard();
    }

    internal async Task<ProductionClaimRecord> ClaimAsync(ProductionPlanRecord plan,
        IReadOnlyList<DurableReferenceSnapshot> snapshots, IReadOnlyDictionary<string, string> graphs,
        ProductionSubmissionJournal journal, ProductionSubmissionJournal.GpuLease gpu, CancellationToken ct)
    {
        var pairing = WorkerLocalPairing.Require(executorId);
        SessionGuard();
        using var client = session.CreateWorkerChallengePreflightClient();
        var claim = await client.ClaimPreparedAsync(plan, WorkerLocalPairing.KeyRoot, executorId, pairing.Fingerprint,
            snapshots, graphs, journal, gpu, ct).ConfigureAwait(false);
        SessionGuard();
        return claim;
    }
}
