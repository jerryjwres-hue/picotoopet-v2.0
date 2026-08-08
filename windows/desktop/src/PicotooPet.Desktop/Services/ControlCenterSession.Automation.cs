using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>项目、自动化、健康与诊断的真实 Mac Core 会话扩展。</summary>
public sealed partial class ControlCenterSession
{
    public async Task<ProjectRecord[]> GetProjectsAsync(CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.GetProjectsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProjectRecord> CreateProjectAsync(
        ProjectCreateRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.CreateProjectAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<ProjectRecord> ArchiveProjectAsync(
        string projectId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.ArchiveProjectAsync(projectId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord[]> GetWorkflowsAsync(CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.GetWorkflowsAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord> CreateWorkflowAsync(
        WorkflowCreateRequest request,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.CreateWorkflowAsync(request, cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord> ReconcileWorkflowAsync(
        string workflowId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.ReconcileWorkflowAsync(workflowId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord> PauseWorkflowAsync(
        string workflowId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.PauseWorkflowAsync(workflowId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord> ResumeWorkflowAsync(
        string workflowId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.ResumeWorkflowAsync(workflowId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<WorkflowRecord> CancelWorkflowAsync(
        string workflowId,
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.CancelWorkflowAsync(workflowId, cancellationToken).ConfigureAwait(false);
    }

    public async Task<AutomationHealthResponse> GetAutomationHealthAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.GetAutomationHealthAsync(cancellationToken).ConfigureAwait(false);
    }

    public async Task<AutomationDiagnosticsResponse> GetAutomationDiagnosticsAsync(
        CancellationToken cancellationToken)
    {
        await using var client = CreateAutomationClient();
        return await client.GetAutomationDiagnosticsAsync(cancellationToken).ConfigureAwait(false);
    }

    private MacCoreAutomationClient CreateAutomationClient()
    {
        ThrowIfDisposed();
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }
        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException("尚未配对 Mac Core。");
        }
        return MacCoreAutomationClient.Create(
            MacCoreClientOptions.CreateDefault(new Uri(baseUrl, UriKind.Absolute), token));
    }
}
