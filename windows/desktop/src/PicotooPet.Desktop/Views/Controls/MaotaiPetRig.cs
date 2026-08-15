namespace PicotooPet.Desktop.Views.Controls;

/// <summary>茅台 Q 版桌宠的本地 WPF 资源目录；只描述展示资源，不持有业务状态。</summary>
public static class MaotaiPetRig
{
    private const string Root = "/Picotoo Pet AI;component/Assets/Pet/Maotai/V1";

    // Rig layers       : same-canvas transparent images used for independent transforms.
    public static string Body         => $"{Root}/rig/body.png";
    public static string Head         => $"{Root}/rig/head.png";
    public static string Tail         => $"{Root}/rig/tail.png";
    public static string LeftPaw      => $"{Root}/rig/paw_left.png";
    public static string RightPaw     => $"{Root}/rig/paw_right.png";
    public static string Laptop       => $"{Root}/rig/laptop.png";
    public static string Drink        => $"{Root}/rig/drink.png";

    // Face overlays    : optional fine-grained expression surfaces for later rig refinements.
    public static string EyesOpen     => $"{Root}/face/eyes_open.png";
    public static string EyesHalf     => $"{Root}/face/eyes_half.png";
    public static string EyesClosed   => $"{Root}/face/eyes_closed.png";
    public static string BrowsFocused => $"{Root}/face/brows_focused.png";
    public static string BrowsAnnoyed => $"{Root}/face/brows_annoyed.png";
    public static string MouthHappy   => $"{Root}/face/mouth_happy.png";
    public static string MouthTired   => $"{Root}/face/mouth_tired.png";
    public static string MouthAnnoyed => $"{Root}/face/mouth_annoyed.png";

    // State posters    : used only for scene transitions/fallbacks and decorative thumbnails.
    public static string WorkingPoster        => $"{Root}/posters/working.png";
    public static string WorkingTiredPoster   => $"{Root}/posters/working_tired.png";
    public static string WorkingAnnoyedPoster => $"{Root}/posters/working_annoyed.png";
    public static string RestingPoster        => $"{Root}/posters/resting.png";
    public static string OfflinePoster        => $"{Root}/posters/offline.png";
}
