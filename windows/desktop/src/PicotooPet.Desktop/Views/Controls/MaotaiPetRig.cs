namespace PicotooPet.Desktop.Views.Controls;

/// <summary>茅台 Q 版桌宠的固定视觉资源键；只描述展示资源，不持有业务状态。</summary>
public static class MaotaiPetRig
{
    // Local override   : installer acceptance packs may place high-detail Q-version PNGs here.
    public static string WorkingFile        => "working.png";
    public static string WorkingTiredFile   => "working_tired.png";
    public static string WorkingAnnoyedFile => "working_annoyed.png";
    public static string RestingFile        => "resting.png";
    public static string OfflineFile        => "offline.png";

    // Rig layers       : live work mode reuses one raster canvas and clips independent regions.
    public static string Body         => WorkingFile;
    public static string Head         => WorkingFile;
    public static string Tail         => WorkingFile;
    public static string LeftPaw      => WorkingFile;
    public static string RightPaw     => WorkingFile;
    public static string Laptop       => WorkingFile;
    public static string Drink        => WorkingFile;

    // Expression keys  : whole-head/raster swaps remain presentation-only and keep real mode unchanged.
    public static string EyesOpen     => WorkingFile;
    public static string EyesHalf     => WorkingTiredFile;
    public static string EyesClosed   => OfflineFile;
    public static string BrowsFocused => WorkingFile;
    public static string BrowsAnnoyed => WorkingAnnoyedFile;
    public static string MouthHappy   => WorkingFile;
    public static string MouthTired   => WorkingTiredFile;
    public static string MouthAnnoyed => WorkingAnnoyedFile;

    // Fallbacks        : bundled resources keep CI/installations functional if optional Q assets are absent.
    public static Uri WorkingFallback => Pack("working_0.png");
    public static Uri RestingFallback => Pack("resting_0.png");
    public static Uri OfflineFallback => Pack("offline_0.png");

    private static Uri Pack(string fileName) => new(
        $"pack://application:,,,/Picotoo Pet AI;component/Assets/Pet/Husky/V1/{fileName}",
        UriKind.Absolute);
}
