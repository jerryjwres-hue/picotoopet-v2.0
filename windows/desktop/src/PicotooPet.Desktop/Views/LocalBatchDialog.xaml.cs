using System.IO;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>选择同一次制作的回执和可选审片记录，自行决定在本机查看或登记到 Mac。</summary>
public partial class LocalBatchDialog : Window
{
    public LocalBatchDialog(bool connected)
    {
        InitializeComponent();
        MaxHeight = SystemParameters.WorkArea.Height;
        Height = Math.Min(Height, MaxHeight);
        Upload.IsEnabled = connected;
        Hint.Text = connected
            ? "离线页直接读取本机视频。导入到 Mac 会登记候选路径、哈希和所选预览。"
            : "离线页可直接对看和记录选择。连接 Mac Core 后可导入。";
    }

    public LocalBatchRequest? Selection { get; private set; }

    private string? Pick(string filter)
    {
        var dialog = new OpenFileDialog { Filter = filter, CheckFileExists = true };
        return dialog.ShowDialog(this) == true ? dialog.FileName : null;
    }
    private void BrowseReceipt(object sender, RoutedEventArgs e) =>
        Receipt.Text = Pick("完成回执|*.result.json") ?? Receipt.Text;
    private void BrowseDecisions(object sender, RoutedEventArgs e) =>
        Decisions.Text = Pick("审片记录|*.json") ?? Decisions.Text;
    private void BrowseRetakes(object sender, RoutedEventArgs e) =>
        Retakes.Text = Pick("重拍回执映射|*.json") ?? Retakes.Text;
    private void BrowseEpisode(object sender, RoutedEventArgs e) =>
        EpisodeFile.Text = Pick("剧集清单|*.json;*.yaml;*.yml") ?? EpisodeFile.Text;
    private void BrowseCutPlan(object sender, RoutedEventArgs e) =>
        CutPlan.Text = Pick("剪辑清单|*.json") ?? CutPlan.Text;
    private void BrowseCutVideo(object sender, RoutedEventArgs e) =>
        CutVideo.Text = Pick("粗剪视频|*.mp4;*.m4v;*.mov;*.mkv;*.webm") ?? CutVideo.Text;

    private LocalBatchProfile CurrentProfile() =>
        new(Receipt.Text.Trim(), EpisodeId.Text.Trim(), EpisodeTitle.Text.Trim(),
            ShotPrefix.Text.Trim(), EpisodeFile.Text.Trim(), Retakes.Text.Trim(),
            CutPlan.Text.Trim(), CutVideo.Text.Trim(), Thumbnail.IsChecked == true,
            Probe.IsChecked == true);

    private void LoadProfile(object sender, RoutedEventArgs e)
    {
        if (Pick("本地审片配置|*.json") is not { } file) return;
        try
        {
            var profile = LocalBatchProfile.Load(file);
            Receipt.Text = profile.Receipt;
            EpisodeId.Text = profile.EpisodeId;
            EpisodeTitle.Text = profile.Title;
            ShotPrefix.Text = profile.Prefix;
            EpisodeFile.Text = profile.EpisodeFile;
            Retakes.Text = profile.RetakesFile;
            CutPlan.Text = profile.CutPlanFile;
            CutVideo.Text = profile.CutVideoFile;
            Thumbnail.IsChecked = profile.Thumbnails;
            Probe.IsChecked = profile.Probe;
            Decisions.Clear();
            Hint.Text = "已载入本机配置。审片记录可按需要另行选择。";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException
            or JsonException or ArgumentException or NotSupportedException)
        {
            Hint.Text = $"无法打开配置。{error.Message}";
        }
    }

    private void SaveProfile(object sender, RoutedEventArgs e)
    {
        if (!Ready()) return;
        var save = new SaveFileDialog
        {
            Title = "保存本地审片配置", Filter = "本地审片配置|*.json",
            DefaultExt = ".json", FileName = "本地审片配置.json", OverwritePrompt = true,
        };
        if (save.ShowDialog(this) != true) return;
        try
        {
            LocalBatchProfile.Save(save.FileName, CurrentProfile());
            Hint.Text = "已保存文件和选项。";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException
            or JsonException or ArgumentException or NotSupportedException)
        {
            Hint.Text = $"无法保存配置。{error.Message}";
        }
    }

    private bool Ready()
    {
        if (!File.Exists(Receipt.Text.Trim()) ||
            (string.IsNullOrWhiteSpace(EpisodeId.Text) && string.IsNullOrWhiteSpace(EpisodeFile.Text)))
        {
            Hint.Text = "请选择完成回执，并填写剧集编号或选择完整剧集清单。";
            return false;
        }
        return true;
    }
    private void CreatePage(object sender, RoutedEventArgs e)
    {
        if (!Ready()) return;
        var save = new SaveFileDialog
        {
            Title = "将离线审片页保存到本机项目", Filter = "离线审片页|*.html", DefaultExt = ".html",
            FileName = "审片.html", OverwritePrompt = true,
            InitialDirectory = new FileInfo(Receipt.Text.Trim()).Directory?.Parent?.Parent?.FullName,
        };
        if (save.ShowDialog(this) == true) Finish(save.FileName);
    }
    private void ImportToMac(object sender, RoutedEventArgs e)
    {
        if (Ready()) Finish(null);
    }
    private void Finish(string? page)
    {
        var profile = CurrentProfile();
        Selection = new LocalBatchRequest(profile.Receipt, profile.EpisodeId, profile.Title,
            profile.Prefix, profile.EpisodeFile, Decisions.Text.Trim(), profile.Thumbnails,
            profile.Probe, page, profile.RetakesFile, profile.CutPlanFile, profile.CutVideoFile);
        DialogResult = true;
    }
}
