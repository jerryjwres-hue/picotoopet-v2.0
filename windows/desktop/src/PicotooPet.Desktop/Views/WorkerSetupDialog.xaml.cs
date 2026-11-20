using System.Windows;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.Views;

/// <summary>只处理一次性 Worker 配对输入；不执行 Mac GPU 审批。</summary>
public partial class WorkerSetupDialog : Window
{
    private readonly bool _secretAlreadySaved;

    public WorkerSetupDialog(string workerId, bool secretAlreadySaved)
    {
        InitializeComponent();
        WorkerIdBox.Text = workerId;
        _secretAlreadySaved = secretAlreadySaved;
    }

    public string WorkerId => WorkerIdBox.Text.Trim();
    public string WorkerSecret => WorkerSecretBox.Password;
    public bool AutoStart => AutoStartCheck.IsChecked == true;

    private void Confirm(object sender, RoutedEventArgs args)
    {
        if (!WorkerProcessManager.IsValidWorkerId(WorkerId))
        {
            MessageBox.Show(this, "Worker ID 只能包含字母、数字、下划线和连字符。");
            return;
        }
        if (!string.IsNullOrEmpty(WorkerSecret)
            && !WorkerProcessManager.IsValidSecret(WorkerSecret))
        {
            MessageBox.Show(this, "Worker 密钥应为 43–256 位 base64url 字符。");
            return;
        }
        if (string.IsNullOrEmpty(WorkerSecret) && !_secretAlreadySaved)
        {
            MessageBox.Show(this, "请首次填写与 Mac Core 对应的独立 Worker 密钥。");
            return;
        }
        DialogResult = true;
    }
}
