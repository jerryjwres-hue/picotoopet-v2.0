// 旁白计划客户端复用现有认证连接，只读取 Core 冻结的 C007A 计划并执行严格响应校验。
using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.Networking;

public sealed partial class MacCoreClient
{
    private const int MaxNarrationPlanBytes = 256 * 1024;

    public async Task<NarrationPlanResponseRecord> GetNarrationPlanAsync(
        string productionJobId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(productionJobId);
        try
        {
            var response = await SendAsync<NarrationPlanResponseRecord>(
                HttpMethod.Get,
                $"api/v1/postproduction/production/{Uri.EscapeDataString(productionJobId)}/narration-plan",
                null,
                "postproduction.narration-plan.get",
                null,
                cancellationToken,
                MaxNarrationPlanBytes).ConfigureAwait(false);
            NarrationPlanContract.Validate(response);
            return response;
        }
        catch (ApiException exception) when (exception.Code == "RESPONSE_TOO_LARGE")
        {
            throw;
        }
        catch (ApiException exception) when (
            exception.Code is "INVALID_RESPONSE" or "EMPTY_RESPONSE")
        {
            throw new ApiException(
                "NARRATION_PLAN_INVALID",
                "Mac Core narration plan contract is invalid.",
                retryable: false,
                exception.TraceId,
                exception.StatusCode);
        }
        catch (NarrationPlanContractException)
        {
            throw new ApiException(
                "NARRATION_PLAN_INVALID",
                "Mac Core narration plan contract is invalid.",
                retryable: false,
                traceId: null,
                statusCode: 200);
        }
        catch (ApiException exception)
        {
            throw new ApiException(
                "NARRATION_HTTP_ERROR",
                $"Mac Core narration endpoint returned HTTP {exception.StatusCode}.",
                exception.Retryable,
                exception.TraceId,
                exception.StatusCode);
        }
    }
}
