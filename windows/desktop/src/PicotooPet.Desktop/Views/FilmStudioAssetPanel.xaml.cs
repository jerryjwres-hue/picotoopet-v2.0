using System.IO;
using System.Windows;
using System.Windows.Controls;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.ViewModels;
using WpfButton = System.Windows.Controls.Button;
using WpfMessageBox = System.Windows.MessageBox;

namespace PicotooPet.Desktop.Views;

/// <summary>明确同意后通过原 Core 通道登记本地素材；不启动预览、Goal 或渲染。</summary>
public partial class FilmStudioAssetPanel : System.Windows.Controls.UserControl
{
    public FilmStudioAssetPanel()
    {
        InitializeComponent();
    }

    private void Project_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        // 01. 必须选择真实活动项目，不以默认目录或草稿推测项目 ID。
        if (ImportCharacterButton is null || ImportSceneButton is null || ImportStyleButton is null)
        {
            return;
        }
        var selected = AssetProjectSelector.SelectedItem is ProjectRecord { Status: "Active" };
        ImportCharacterButton.IsEnabled = selected;
        ImportSceneButton.IsEnabled = selected;
        ImportStyleButton.IsEnabled = selected;
    }

    private async void RefreshProjects_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not FilmStudioPageViewModel model || !AssetControls.IsEnabled)
        {
            return;
        }

        AssetControls.IsEnabled = false;
        try
        {
            var selectedId = (AssetProjectSelector.SelectedItem as ProjectRecord)?.ProjectId;
            var projects = await model.GetAssetProjectsAsync(CancellationToken.None);
            AssetProjectSelector.ItemsSource = projects;
            AssetProjectSelector.SelectedItem = projects.FirstOrDefault(p => p.ProjectId == selectedId);
            AssetStatus.Text = projects.Count == 0
                ? "没有活动项目；请先在高级 → 项目创建。"
                : $"已读取 {projects.Count} 个活动项目，请选择一个。";
        }
        catch (Exception)
        {
            AssetProjectSelector.ItemsSource = null;
            AssetStatus.Text = "未能读取项目，请检查 Core 连接后重试。";
        }
        finally
        {
            AssetControls.IsEnabled = true;
        }
    }

    private async void ImportAsset_Click(object sender, RoutedEventArgs e)
    {
        if (DataContext is not FilmStudioPageViewModel model
            || AssetProjectSelector.SelectedItem is not ProjectRecord { Status: "Active" } project
            || sender is not WpfButton { Tag: string role }
            || role is not ("character" or "scene" or "style")
            || !AssetControls.IsEnabled)
        {
            return;
        }

        var originalDraft = model.Creative.StoryPackJson;
        if (string.IsNullOrWhiteSpace(originalDraft))
        {
            AssetStatus.Text = "请先在下方载入示例或打开自己的 StoryPack JSON，再选择素材。";
            return;
        }

        // 02. 原生文件选择器只读用户选中的单一文件；不扫描目录。
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Filter = role == "style"
                ? "风格文件|*.png;*.jpg;*.jpeg;*.webp;*.txt;*.md;*.json"
                : "图片文件|*.png;*.jpg;*.jpeg;*.webp",
            CheckFileExists = true,
            Multiselect = false,
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }

        AssetControls.IsEnabled = false;
        var importStarted = false;
        try
        {
            var mediaType = Path.GetExtension(dialog.FileName).ToUpperInvariant() switch
            {
                ".PNG" => "image/png",
                ".JPG" or ".JPEG" => "image/jpeg",
                ".WEBP" => "image/webp",
                ".TXT" or ".MD" when role == "style" => "text/plain",
                ".JSON" when role == "style" => "application/json",
                _ => throw new InvalidDataException("Unsupported asset extension"),
            };

            byte[] data;
            using (var stream = new FileStream(
                dialog.FileName, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (stream.Length is <= 0 or > MacCoreClient.MaxStudioAssetBytes)
                {
                    throw new InvalidDataException("Asset size");
                }
                data = new byte[(int)stream.Length];
                await stream.ReadExactlyAsync(data);
                if (stream.ReadByte() != -1)
                {
                    throw new InvalidDataException("Asset changed");
                }
            }

            // 03. 核对本次文件、项目与角色，并要求单次明确同意；默认拒绝。
            var roleLabel = role switch { "character" => "角色", "scene" => "场景", _ => "风格" };
            var answer = WpfMessageBox.Show(
                Window.GetWindow(this),
                $"项目：{project.Title}\n素材：{Path.GetFileName(dialog.FileName)}\n类型：{roleLabel}\n大小：{data.Length:N0} 字节\n\n将副本登记到配对 Mac Core？不移动原文件，不通过 Owner / MASTER，不创建任务或解除 GPU HOLD。",
                "确认本地素材登记",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question,
                MessageBoxResult.No);

            if (answer != MessageBoxResult.Yes)
            {
                AssetStatus.Text = "已取消，未发送素材。";
                return;
            }

            // 04. 回执由客户端独立校验；绑定只更新当前相同草稿，绝不自动提交。
            if (!model.Creative.TryBeginAssetImport(originalDraft))
            {
                AssetStatus.Text = "草稿已改变或创意操作进行中；未发送素材，请重试。";
                return;
            }
            importStarted = true;
            AssetStatus.Text = "正在核验并登记本地素材副本……";
            var id = await model.RegisterAssetAsync(
                project.ProjectId, role, mediaType, data, CancellationToken.None);

            var bound = model.Creative.TryBindImportedAsset(originalDraft, role, id);
            AssetStatus.Text = bound
                ? $"{roleLabel}已登记并绑定。请重新点击只读检查；Owner 未批准，GPU HOLD。\n{id}"
                : $"{roleLabel}已登记，但草稿已变化或无法绑定；未覆盖草稿。再次选择同一文件可幂等重试。\n{id}";
        }
        catch (Exception)
        {
            // 网络失败也可能是登记成功但回执丢失；不作成功/未写入断言。
            AssetStatus.Text = "登记未获可验证回执；请确认连接、素材不超过 16 MiB 后重试原文件。未自动绑定或授权生产。";
        }
        finally
        {
            if (importStarted)
            {
                model.Creative.EndAssetImport();
            }
            AssetControls.IsEnabled = true;
        }
    }
}
