namespace PicotooPet.Desktop.Navigation;

/// <summary>导航显示项及其当前能力可用性。</summary>
public sealed record NavigationItem(
    NavigationRoute Route,
    string Title,
    bool IsAvailable,
    string AvailabilityMessage);
