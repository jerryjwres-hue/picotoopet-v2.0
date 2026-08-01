using PicotooPet.Desktop.Core.Contracts;

namespace PicotooPet.Desktop.Core.State;

/// <summary>独立维护服务端显式能力；未知能力始终保守关闭。</summary>
public sealed class CapabilityStateStore
{
    private readonly object _gate = new();
    private CapabilitySnapshot _snapshot = CapabilitySnapshot.Legacy22;

    /// <summary>能力状态提交后发布新的不可变快照。</summary>
    public event EventHandler<CapabilitySnapshot>? SnapshotChanged;

    /// <summary>当前能力快照。</summary>
    public CapabilitySnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                return _snapshot;
            }
        }
    }

    /// <summary>提交服务端返回的类型化能力响应。</summary>
    public void Set(CapabilitiesResponse response)
    {
        ArgumentNullException.ThrowIfNull(response);

        CapabilitySnapshot snapshot;
        lock (_gate)
        {
            snapshot = new CapabilitySnapshot(
                response.SchemaVersion,
                response.Features,
                response.ContractVersions,
                response.CloudUpload);
            _snapshot = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }

    /// <summary>能力接口不可用或不兼容时恢复 2.2 保守能力集。</summary>
    public void SetLegacy22()
    {
        CapabilitySnapshot snapshot;
        lock (_gate)
        {
            snapshot  = CapabilitySnapshot.Legacy22;
            _snapshot = snapshot;
        }
        SnapshotChanged?.Invoke(this, snapshot);
    }
}
