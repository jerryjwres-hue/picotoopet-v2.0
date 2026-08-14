namespace PicotooPet.Desktop.Controls.PetMascot;

/// <summary>茅台第一版只保留轻量展示状态，不承载任务或 Worker 业务逻辑。</summary>
public enum PetMascotState
{
    Idle,
    Working,
    Success,
    Away,
    Bath,
    Offline,
}
