using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.DevBroker;
using PicotooPet.Desktop.Core.Networking;

namespace PicotooPet.Desktop.Services;

/// <summary>把固定 Mock Dev Broker 进程、Mac Core 事实和 Return 导回编排为一个闭环。</summary>
public sealed partial class ControlCenterSession
{
    private readonly object _brokerExecutionGate = new();
    private CancellationTokenSource? _activeBrokerCancellation;
    private string? _activeBrokerSessionId;

    /// <summary>读取最多一百条 Broker Session 固定安全投影。</summary>
    public async Task<BrokerSessionRecord[]> GetBrokerSessionsAsync(
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        await using var client = CreateBrokerClient();
        return await client.GetSessionsAsync(cancellationToken).ConfigureAwait(false);
    }

    /// <summary>预留、启动、约束子进程并提交固定 Mock Return。</summary>
    public async Task<BrokerSessionRecord> RunMockBrokerAsync(
        HandoffRecord handoff,
        string idempotencyKey,
        IProgress<BrokerSessionRecord> progress,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(handoff);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        ArgumentNullException.ThrowIfNull(progress);
        if (!string.Equals(handoff.Status, "approved", StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                "只有 approved Handoff 可以启动固定 Mock Dev Broker。");
        }

        var executionCancellation = CancellationTokenSource.CreateLinkedTokenSource(
            _lifetime.Token,
            cancellationToken);
        lock (_brokerExecutionGate)
        {
            if (_activeBrokerCancellation is not null)
            {
                executionCancellation.Dispose();
                throw new InvalidOperationException("已有 Mock Broker Session 正在运行。");
            }
            _activeBrokerCancellation = executionCancellation;
        }

        BrokerSessionCreateResult? reserved = null;
        try
        {
            await using var client = CreateBrokerClient();
            reserved = await client.ReserveMockAsync(
                handoff.HandoffId,
                idempotencyKey,
                executionCancellation.Token).ConfigureAwait(false);
            lock (_brokerExecutionGate)
            {
                _activeBrokerSessionId = reserved.Record.SessionId;
            }
            progress.Report(reserved.Record);

            var running = await client.StartAsync(
                reserved.Record.SessionId,
                $"{idempotencyKey}-start",
                executionCancellation.Token).ConfigureAwait(false);
            progress.Report(running);

            MockBrokerReturnEnvelope envelope;
            try
            {
                envelope = await DevBrokerProcessRunner.RunAsync(
                    reserved,
                    handoff,
                    executionCancellation.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (executionCancellation.IsCancellationRequested)
            {
                var cancelled = await client.CancelAsync(
                    reserved.Record.SessionId,
                    $"{idempotencyKey}-cancel",
                    CancellationToken.None).ConfigureAwait(false);
                progress.Report(cancelled);
                return cancelled;
            }
            catch (BrokerProcessException exception) when (
                string.Equals(exception.Code, "BROKER_TIMED_OUT", StringComparison.Ordinal))
            {
                await using var terminalClient = CreateBrokerTerminalClient();
                var timedOut = await terminalClient.SetTerminalAsync(
                    reserved.Record.SessionId,
                    BrokerTerminalAction.Timeout,
                    $"{idempotencyKey}-timeout",
                    CancellationToken.None).ConfigureAwait(false);
                progress.Report(timedOut);
                return timedOut;
            }
            catch (BrokerProcessException exception)
            {
                _logger.Error("固定 Mock Broker 子进程失败", exception);
                await using var terminalClient = CreateBrokerTerminalClient();
                var failed = await terminalClient.SetTerminalAsync(
                    reserved.Record.SessionId,
                    BrokerTerminalAction.Fail,
                    $"{idempotencyKey}-fail",
                    CancellationToken.None).ConfigureAwait(false);
                progress.Report(failed);
                return failed;
            }

            var completed = await client.SubmitReturnAsync(
                reserved.Record.SessionId,
                envelope,
                reserved.Capability,
                $"{idempotencyKey}-return",
                executionCancellation.Token).ConfigureAwait(false);
            progress.Report(completed);
            return completed;
        }
        finally
        {
            lock (_brokerExecutionGate)
            {
                if (ReferenceEquals(_activeBrokerCancellation, executionCancellation))
                {
                    _activeBrokerCancellation = null;
                    _activeBrokerSessionId     = null;
                }
            }
            executionCancellation.Dispose();
        }
    }

    /// <summary>取消当前 Job Object 进程树，并提交 Mac Core cancelled 事实。</summary>
    public async Task<BrokerSessionRecord> CancelBrokerAsync(
        string sessionId,
        string idempotencyKey,
        CancellationToken cancellationToken)
    {
        ThrowIfDisposed();
        ArgumentException.ThrowIfNullOrWhiteSpace(sessionId);
        ArgumentException.ThrowIfNullOrWhiteSpace(idempotencyKey);
        CancellationTokenSource? activeCancellation;
        lock (_brokerExecutionGate)
        {
            activeCancellation = string.Equals(
                    _activeBrokerSessionId,
                    sessionId,
                    StringComparison.Ordinal)
                ? _activeBrokerCancellation
                : null;
        }
        activeCancellation?.Cancel();

        await using var client = CreateBrokerClient();
        return await client.CancelAsync(
            sessionId,
            idempotencyKey,
            cancellationToken).ConfigureAwait(false);
    }

    /// <summary>会话释放前停止仍在运行的固定 Broker 进程树。</summary>
    private void CancelActiveBrokerExecution()
    {
        lock (_brokerExecutionGate)
        {
            _activeBrokerCancellation?.Cancel();
        }
    }

    private MacCoreBrokerClient CreateBrokerClient()
    {
        var connection = ReadBrokerConnection();
        return MacCoreBrokerClient.Create(connection.BaseUri, connection.Token);
    }

    private MacCoreBrokerTerminalClient CreateBrokerTerminalClient()
    {
        var connection = ReadBrokerConnection();
        return MacCoreBrokerTerminalClient.Create(connection.BaseUri, connection.Token);
    }

    private (Uri BaseUri, string Token) ReadBrokerConnection()
    {
        string baseUrl;
        lock (_snapshotGate)
        {
            baseUrl = _macBaseUrl;
        }

        var token = _tokenStore.Read();
        if (string.IsNullOrWhiteSpace(token))
        {
            throw new InvalidOperationException(
                "尚未配对 Mac Core；设备令牌只允许从 Credential Manager 读取。");
        }
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var baseUri))
        {
            throw new InvalidOperationException("当前 Mac Core 地址格式无效。");
        }
        return (baseUri, token);
    }
}
