using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

public interface IReferenceBatchGateway
{
    Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken);
    Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken);
}

public sealed partial class MacCoreClient : IReferenceBatchGateway
{
    public async Task<ReferenceBatchReceipt> RegisterReferenceBatchAsync(
        ReferenceBatchRequest request, string idempotencyKey, CancellationToken cancellationToken)
    {
        ReferenceBatchValidation.ValidateRequest(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        if (idempotencyKey.Length > 200 || idempotencyKey.Any(char.IsControl))
        {
            throw new ArgumentException("REFERENCE_IDEMPOTENCY_KEY_INVALID", nameof(idempotencyKey));
        }
        // Freeze the selected array before crossing the asynchronous transport boundary.
        var snapshot = request with { SelectedReferences = request.SelectedReferences.ToArray() };
        var receipt = await SendAsync<ReferenceBatchReceipt>(
            HttpMethod.Post, "api/v1/production/references/batches", snapshot,
            "reference-batch-register", idempotencyKey, cancellationToken, 128 * 1024).ConfigureAwait(false);
        ReferenceBatchValidation.ValidateReceipt(snapshot, receipt);
        return receipt;
    }

    public async Task<ReferenceBatchReceipt> GetReferenceBatchAsync(string approvalId, CancellationToken cancellationToken)
    {
        if (!ReferenceBatchValidation.IsUuid(approvalId))
        {
            throw new ArgumentException("REFERENCE_APPROVAL_ID_INVALID", nameof(approvalId));
        }
        var receipt = await SendAsync<ReferenceBatchReceipt>(
            HttpMethod.Get, $"api/v1/production/references/batches/{Uri.EscapeDataString(approvalId)}", null,
            "reference-batch-get", null, cancellationToken, 128 * 1024).ConfigureAwait(false);
        ReferenceBatchValidation.ValidateReceiptIdentity(receipt);
        if (receipt.ApprovalId != approvalId)
        {
            throw new InvalidDataException("REFERENCE_BATCH_RECEIPT_MISMATCH");
        }
        return receipt;
    }
}
