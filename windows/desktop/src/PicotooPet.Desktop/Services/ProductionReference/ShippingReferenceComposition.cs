using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Production;

namespace PicotooPet.Desktop.Services.ProductionReference;

/// <summary>
/// Formal same-EXE composition of paired Core authority and the existing snapshot store.
/// An authenticated reference read and measured bytes are NOT independently verified
/// Worker proof. Controller #152/PR #154 has not frozen identity/key/nonce/transaction
/// validation, so no caller-provided flag, environment switch or local measurement
/// can enable this production boundary. There is deliberately no proof issuer here.
/// </summary>
internal sealed class ShippingReferenceComposition(ControlCenterSession session, string executorId)
{
    public ProductionReferenceSnapshotStore CreateSnapshotStore(string inputRoot) =>
        new(inputRoot, (plan, task, digest) => new CoreReferenceApprovalSource(
            session, plan.ProductionJobId, task.ProductionTaskId, digest));

    public void RequireVerifiedWorkerProof(ProductionPlanRecord plan)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(executorId);
        ProductionExecutionService.ValidateV11FrozenReferenceIdentities(plan.ProductionJobId, plan);
        // Do not invent a device identity from executorId/machine name, sign with the
        // shared UI bearer, or infer a Core one-use admission from successful GETs.
        throw new ProductionWorkerException("I2V_CROSS_ENDPOINT_WORKER_PROOF_REQUIRED");
    }
}
