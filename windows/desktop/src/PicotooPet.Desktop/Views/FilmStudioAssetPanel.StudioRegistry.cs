using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Windows;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.ViewModels;
using WpfMessageBox = System.Windows.MessageBox;

namespace PicotooPet.Desktop.Views;

/// <summary>已有 FLUX.2 茅台 LoRA 的 Windows 摘要登记；不上传模型、不训练、不推理。</summary>
public partial class FilmStudioAssetPanel
{
    private const long MaxSelectedLoraBytes = 4L * 1024 * 1024 * 1024;
    private const long MaotaiLoraV2Bytes = 46_223_616;
    private const string MaotaiLoraV2Sha256 =
        "5972e7f782e3e4ed16b764441fdb66d638cb6a8ba85fb8226d95feeb98e8eb70";

    private async void RegisterLora_Click(object sender, RoutedEventArgs e)
    {
        // 01. 只接受手动选择的真实项目和独立 .safetensors 文件。
        if (DataContext is not FilmStudioPageViewModel model
            || AssetProjectSelector.SelectedItem is not ProjectRecord { Status: "Active" } project
            || !AssetControls.IsEnabled)
        {
            return;
        }

        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Filter = "FLUX LoRA 文件|*.safetensors",
            CheckFileExists = true,
            Multiselect = false,
            Title = "选择既有茅台 LoRA v2（只核验文件摘要，不上传模型）",
        };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true)
        {
            return;
        }

        AssetControls.IsEnabled = false;
        try
        {
            var filename = Path.GetFileName(dialog.FileName);
            if (!string.Equals(Path.GetExtension(filename), ".safetensors",
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Only safetensors LoRA");
            }

            // 02. 锁定选定文件的只读句柄，一次顺序 SHA256；在网络
            //     回执完成前持续持有，避免用户授权后文件被其他程序改写。
            await using var stream = new FileStream(
                dialog.FileName, FileMode.Open, FileAccess.Read, FileShare.Read,
                bufferSize: 1024 * 1024, options: FileOptions.SequentialScan);
            var bytes = stream.Length;
            if (bytes is <= 0 or > MaxSelectedLoraBytes)
            {
                throw new InvalidDataException("LoRA size out of range");
            }
            var digest = Convert.ToHexStringLower(
                await SHA256.HashDataAsync(stream, CancellationToken.None));
            if (stream.Length != bytes || stream.Position != bytes)
            {
                throw new InvalidDataException("LoRA bytes changed during verification");
            }
            // 03. 本按钮仅登记已核实的 v2。旧版 v1 已作废，
            //     不允许误把任意其他 LoRA 当成当前茅台身份资产。
            if (bytes != MaotaiLoraV2Bytes
                || !string.Equals(digest, MaotaiLoraV2Sha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException("Selected LoRA does not match pinned Maotai v2");
            }

            // 04. 显示完整 SHA256 和「只提交摘要」的明确同意；取消无 HTTP。
            var answer = WpfMessageBox.Show(
                Window.GetWindow(this),
                $"项目：{project.Title}\n文件：{filename}\n大小：{bytes:N0} 字节\nSHA256：{digest}"
                + "\n\n只将摘要、大小、文件名和核验时间登记到配对 Mac Core。"
                + "\n原 LoRA 文件保留在 Windows，不上传字节。"
                + "\n本步骤不会批准资产、运行 GPU 或解除 HOLD。确认登记？",
                "确认登记现有 LoRA 摘要",
                MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
            if (answer != MessageBoxResult.Yes)
            {
                AssetStatus.Text = "已取消 LoRA 登记；未发送摘要。";
                return;
            }

            // 04. 秒精度的 UTC 时间可被 Pydantic 原样回传；不传路径。
            var evidence = new StudioWindowsByteEvidence(
                filename, DateTimeOffset.UtcNow.ToString(
                    "yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture));
            var claim = await model.RegisterWindowsLoraAsync(
                project.ProjectId, digest, bytes, evidence, CancellationToken.None);

            AssetStatus.Text = "LoRA 摘要已记录（Mac 未核验 Windows 文件字节）。"
                + "\nOwner 未批准、GPU HOLD。资产 ID：" + claim.ArtifactId;

            // 05. 只有重新确认才创建 Pending 请求；无自动 Owner 决定。
            var approval = await OfferOwnerApprovalRequestAsync(
                model, "LoRA v2", claim.ArtifactId, digest, evidence);
            if (!string.IsNullOrWhiteSpace(approval))
            {
                AssetStatus.Text = approval;
            }
        }
        catch (InvalidDataException)
        {
            AssetStatus.Text = "所选文件不是已核验的茅台 LoRA v2（完整 SHA 或字节数不一致）。"
                + "拒绝登记，不能使用已作废的 v1。GPU HOLD。";
        }
        catch (Exception)
        {
            // 06. 超时可能发生在服务端提交之后；不得假报失败或成功。
            //     原文件无改动，可由用户选择同一文件进行幂等登记。
            AssetStatus.Text = "LoRA 登记/审批请求未得到完整可验证回执；"
                + "请核对 Core 连接并使用同一原文件重试。"
                + "未自动批准，不会调用 GPU。";
        }
        finally
        {
            AssetControls.IsEnabled = true;
        }
    }

    private async Task<string?> OfferOwnerApprovalRequestAsync(
        FilmStudioPageViewModel model, string assetName, string artifactId,
        string sha256, StudioWindowsByteEvidence? windowsEvidence)
    {
        // 07. 第二次独立明确同意只是「申请」，审批中心仍需 Owner 决定。
        var answer = WpfMessageBox.Show(
            Window.GetWindow(this),
            $"资产：{assetName}\nCore ID：{artifactId}\nSHA256：{sha256}"
            + "\n\n是否向现有审批中心发起该资产的 Owner 审核请求？"
            + "\n这不会代表 Owner 批准，不会激活生产或 GPU。",
            "单独确认发起 Owner 审核",
            MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
        if (answer != MessageBoxResult.Yes)
        {
            return null;
        }
        var result = await model.RequestAssetOwnerApprovalAsync(
            artifactId, sha256, windowsEvidence, CancellationToken.None);
        return result.Status == "Approved"
            ? $"此前已有有效 Owner 批准记录；本次没有替用户点击批准。GPU HOLD。\n{artifactId}"
            : $"已发起 Owner 待审批请求：{result.ApprovalId}。请在审批中心明确审阅。GPU HOLD。\n{artifactId}";
    }
}
