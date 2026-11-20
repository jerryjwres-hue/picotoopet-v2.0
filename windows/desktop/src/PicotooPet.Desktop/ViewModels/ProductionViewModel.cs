using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Encodings.Web;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;
using PicotooPet.Desktop.Core.Security;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

public sealed class ProductionViewModel : ObservableObject
{
    private static readonly JsonSerializerOptions QcFormat = new()
    {
        WriteIndented = true,
        Encoder = JavaScriptEncoder.Create(System.Text.Unicode.UnicodeRanges.All),
    };

    private readonly Func<MacCoreClient?> _client;
    private readonly Func<CancellationToken> _token;
    private readonly DesktopSettingsStore? _settingsStore;
    private readonly WorkerProcessManager? _workerManager;
    private readonly ITokenStore? _workerSecretStore;
    private readonly Func<string>? _coreAddress;
    private readonly Func<string?>? _deviceToken;
    private string _workerRuntimeStatus = "Worker 尚未启动，GPU 默认 HOLD。";
    private string _workerId = "edit-workstation";
    private string _workerProjectRoot = "";
    private EpisodeSummary[] _episodes = [];
    private ShotReview[] _shots = [];
    private CandidateViewModel[] _candidates = [];
    private EpisodeSummary? _episode;
    private ShotReview? _shot;
    private CandidateViewModel? _candidate;
    private bool _active;
    private bool _refreshing;
    private bool _refreshPending;
    private bool _canAssemble;
    private bool _saving;
    private bool _hasNoteConflict;
    private string _note = "";
    private string _message = "";
    private readonly Dictionary<string, BitmapSource> _previews = new(StringComparer.Ordinal);

    public ProductionViewModel(
        Func<MacCoreClient?> client, Func<CancellationToken> token,
        DesktopSettingsStore? settingsStore = null,
        WorkerProcessManager? workerManager = null,
        ITokenStore? workerSecretStore = null,
        Func<string>? coreAddress = null,
        Func<string?>? deviceToken = null)
    {
        _client = client;
        _token = token;
        _settingsStore = settingsStore;
        _workerManager = workerManager;
        _workerSecretStore = workerSecretStore;
        _coreAddress = coreAddress;
        _deviceToken = deviceToken;
        RefreshCommand = new AsyncRelayCommand(RefreshAsync, ReportError, () => _client() is not null);
        SyncApprovedFramesCommand = new AsyncRelayCommand(
            SyncApprovedFramesAsync, ReportError,
            () => !_saving && HasConnection && HasWorkerProjectRoot);
        PickCommand = new AsyncRelayCommand(() => DecideAsync("pick"), ReportError, () => CanDecide() && Candidate?.CanPick == true);
        RedoCommand = new AsyncRelayCommand(() => DecideAsync("redo"), ReportError, () => CanDecide() && Candidate?.CanRedo == true);
        RejectCommand = new AsyncRelayCommand(() => DecideAsync("reject"), ReportError, CanDecide);
        AssembleCommand = new AsyncRelayCommand(
            AssembleAsync, ReportError, () => _canAssemble && !_saving && _client() is not null);
        PlayCommand = new AsyncRelayCommand(PlayAsync, ReportError, () => Candidate?.CanPlay == true);
        KeepDraftCommand = new AsyncRelayCommand(() => ResolveNote(false), ReportError);
        UseMacNoteCommand = new AsyncRelayCommand(() => ResolveNote(true), ReportError);
    }

    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand SyncApprovedFramesCommand { get; }
    public AsyncRelayCommand PickCommand { get; }
    public AsyncRelayCommand RedoCommand { get; }
    public AsyncRelayCommand RejectCommand { get; }
    public AsyncRelayCommand AssembleCommand { get; }
    public AsyncRelayCommand PlayCommand { get; }
    public AsyncRelayCommand KeepDraftCommand { get; }
    public AsyncRelayCommand UseMacNoteCommand { get; }

    public bool IsActive
    {
        get => _active;
        set
        {
            if (SetProperty(ref _active, value) && value)
            {
                QueueRefresh();
            }
        }
    }

    public IReadOnlyList<EpisodeSummary> Episodes => _episodes;
    public IReadOnlyList<ShotReview> Shots => _shots;
    public IReadOnlyList<CandidateViewModel> Candidates => _candidates;

    public EpisodeSummary? Episode
    {
        get => _episode;
        set
        {
            if (SetProperty(ref _episode, value))
            {
                ApplyReview(null);
                QueueRefresh();
            }
        }
    }

    public ShotReview? Shot
    {
        get => _shot;
        set
        {
            if (SetProperty(ref _shot, value))
            {
                SetCandidates();
            }
        }
    }

    public CandidateViewModel? Candidate
    {
        get => _candidate;
        set
        {
            var previousId = _candidate?.Record.ArtifactId;
            if (SetProperty(ref _candidate, value))
            {
                if (previousId != value?.Record.ArtifactId)
                {
                    Note = value?.Record.Note ?? "";
                    HasNoteConflict = false;
                }
                RaisePropertyChanged(nameof(QcText));
                RaisePropertyChanged(nameof(CandidateHint));
                RaisePropertyChanged(nameof(PickLabel));
                UpdateCommands();
            }
        }
    }

    public string QcText => Candidate?.QcText ?? "选择候选查看质检报告。";
    public string PickLabel => Candidate?.IsManualGate == true ? "人工复核选用" : "选用";
    public string CandidateHint => Candidate?.CanPlay == true ? "视频文件将用本机播放器打开。" : "";
    public bool CanOpenBatch => !_saving;
    public bool HasConnection => _client() is not null;
    public string WorkerProjectRoot => _workerProjectRoot;
    public string CurrentWorkerId => _workerId;
    public bool HasStoredWorkerKey => !string.IsNullOrWhiteSpace(_workerSecretStore?.Read());
    public string WorkerRuntimeStatus
    {
        get => _workerRuntimeStatus;
        private set => SetProperty(ref _workerRuntimeStatus, value);
    }
    public bool HasWorkerProjectRoot => IsValidWorkerRoot(_workerProjectRoot);
    public string WorkerProjectStatus => HasWorkerProjectRoot
        ? $"视频项目：{Path.GetFileName(Path.TrimEndingDirectorySeparator(_workerProjectRoot))}"
        : "未选择视频项目目录（仅首次需要）";


    /// <summary>恢复已有非敏感视频项目配置；不扫描用户目录或执行 Worker。</summary>
    public void SetWorkerProjectRoot(string? root)
    {
        _workerProjectRoot = root ?? "";
        RaisePropertyChanged(nameof(WorkerProjectRoot));
        RaisePropertyChanged(nameof(WorkerProjectStatus));
        RaisePropertyChanged(nameof(HasWorkerProjectRoot));
        UpdateCommands();
    }

    private static bool IsValidWorkerRoot(string? root)
    {
        if (string.IsNullOrWhiteSpace(root) ||
            !Path.IsPathFullyQualified(root) ||
            root.StartsWith(@"\\", StringComparison.Ordinal) ||
            !Directory.Exists(root))
        {
            return false;
        }
        // 只接受已有的本地 Worker 项目，不把普通文件夹误当视频工程。
        return Directory.Exists(Path.Combine(root, "_queue")) ||
               Directory.Exists(Path.Combine(root, "17_静态首帧板V2"));
    }

    /// <summary>用户只需选一次已有 Worker 项目；路径使用既有非敏感设置文件保存。</summary>
    public async Task ChooseWorkerProjectAsync(string folder)
    {
        var root = Path.GetFullPath(folder);
        if (!IsValidWorkerRoot(root))
        {
            throw new InvalidOperationException(
                "请选择已有视频项目根目录（应包含 _queue 或 17_静态首帧板V2）。");
        }
        if (_settingsStore is null)
        {
            throw new InvalidOperationException("当前 Studio 未配置视频项目设置存储。");
        }
        // 先保存成功，再更新 UI；没有模型加载或 GPU 操作。
        var old = await _settingsStore.LoadAsync(CancellationToken.None);
        await _settingsStore.SaveAsync(
            old with { WindowsProjectRoot = root }, CancellationToken.None);
        SetWorkerProjectRoot(root);
        Message = "视频项目目录已保存。此设置只需进行一次。";
    }

    /// <summary>只有用户曾显式勾选自动启动，才在再次打开 Studio 后复用同一 Bridge。</summary>
    public async Task TryAutoStartWorkerAsync(DesktopSettings settings)
    {
        _workerId = settings.WorkerId;
        if (!settings.WorkerAutoStart)
        {
            WorkerRuntimeStatus = "Worker 自动启动尚未启用；GPU 保持 Mac Core 门禁。";
            return;
        }
        try
        {
            await StartWorkerAsync(settings.WorkerId, "", true);
        }
        catch (Exception error)
        {
            // 登录与审片不因 Worker 环境缺失而中断；不能假装后台已经启动。
            WorkerRuntimeStatus = $"Worker 自动启动被阻止：{error.Message}";
        }
    }

    /// <summary>首次输入密钥后存 Credential Manager；正常运行不再要求命令行。</summary>
    public async Task StartWorkerAsync(string workerId, string newSecret, bool autoStart)
    {
        if (_workerManager is null || _workerSecretStore is null
            || _settingsStore is null || _coreAddress is null || _deviceToken is null)
            throw new InvalidOperationException("此 Studio 未配置 Worker 进程管理。");

        var key = string.IsNullOrEmpty(newSecret) ? _workerSecretStore.Read() : newSecret;
        if (key is null || !WorkerProcessManager.IsValidSecret(key))
            throw new InvalidOperationException("请先提供安全保存的 Worker 独立配对密钥。");

        var coreUrl = _coreAddress();
        var deviceToken = _deviceToken() ?? "";
        var status = await Task.Run(() => _workerManager.Start(
            coreUrl, _workerProjectRoot, workerId, deviceToken, key));
        if (!string.IsNullOrEmpty(newSecret))
            _workerSecretStore.Save(newSecret);
        var existing = await _settingsStore.LoadAsync(CancellationToken.None);
        await _settingsStore.SaveAsync(
            existing with { WorkerId = workerId, WorkerAutoStart = autoStart },
            CancellationToken.None);
        _workerId = workerId;
        WorkerRuntimeStatus = status;
    }

    /// <summary>只操纵现有 Worker 的 pause-new 标记，不终止在途 GPU/Journal。</summary>
    public async Task SetWorkerNewTasksPausedAsync(bool paused)
    {
        if (_workerManager is null)
            throw new InvalidOperationException("Worker 进程管理不可用。");
        await Task.Run(() => _workerManager.SetNewLeasesPaused(paused));
        WorkerRuntimeStatus = paused
            ? "本地 Worker 已暂停领取新任务；已运行的任务继续保留。"
            : "已解除本地暂停；Mac Core Owner/MASTER 和冻结 Plan 门禁仍有效。";
    }

    /// <summary>只领取 Mac Owner 已批准的素材，按 SHA 落地；绝不自动提交视频任务。</summary>
    private async Task SyncApprovedFramesAsync()
    {
        var client = _client();
        if (client is null || !HasWorkerProjectRoot || _saving)
        {
            return;
        }
        _saving = true;
        UpdateCommands();
        try
        {
            Message = "正在检查 Mac 上已审核的首帧素材并同步…";
            var receipt = await client.ClaimAndStagePendingFramesAsync(
                _workerProjectRoot, _token());
            Message = receipt is null
                ? "暂无已审核、待同步的首帧素材。请先在 Mac 端完成主人审核。"
                : $"素材同步完成：{receipt.Bindings.Count} 项镜头引用已按 SHA 验证。" +
                  (receipt.CoreStagingStatus == "WINDOWS_STAGING_REPORTED_FOR_FROZEN_PLAN"
                      ? " 已对接 Mac 冻结计划，GPU 仍关闭。"
                      : " 生产计划未冻结或未关联，GPU 仍关闭。");
        }
        finally
        {
            _saving = false;
            UpdateCommands();
        }
    }

    public bool HasNoteConflict
    {
        get => _hasNoteConflict;
        private set => SetProperty(ref _hasNoteConflict, value);
    }

    private Task ResolveNote(bool useMac)
    {
        if (useMac) Note = Candidate?.Record.Note ?? "";
        HasNoteConflict = false;
        UpdateCommands();
        return Task.CompletedTask;
    }

    public async Task ProcessBatchAsync(LocalBatchRequest options)
    {
        if (_saving) return;
        _saving = true;
        UpdateCommands();
        var client = _client();
        var token = options.PagePath is null ? _token() : CancellationToken.None;
        try
        {
            Message = "正在核对完成回执、视频和原始种子…";
            var manifest = await LocalVideoBatch.PrepareAsync(options, token);
            if (options.PagePath is { } page)
            {
                using var browser = Process.Start(new ProcessStartInfo(page) { UseShellExecute = true });
                Message = $"已打开离线审片页。文件保存在 {page}";
                return;
            }
            if (client is null || !ReferenceEquals(client, _client()))
                throw new InvalidOperationException("请连接 Mac Core 后再次导入。");
            var result = await client.ImportBatchAsync(manifest, token);
            await RefreshAsync();
            Episode = Episodes.FirstOrDefault(x => x.EpisodeId == result.EpisodeId) ?? Episode;
            Message = $"剧集 {result.EpisodeId} 新增 {result.InsertedCount} 条，已有 {result.ExistingCount} 条。";
            if (result.UpdatedCount > 0) Message += $" 已补入 {result.UpdatedCount} 条离线审片记录。";
            if (result.ConflictCount > 0) Message += $" {result.ConflictCount} 条与 Mac 审片冲突，已保留 Mac 记录。";
        }
        catch (Exception ex) { ReportError(ex); }
        finally
        {
            _saving = false;
            UpdateCommands();
        }
    }

    public string Note
    {
        get => _note;
        set => SetProperty(ref _note, value);
    }

    public string Message
    {
        get => _message;
        private set => SetProperty(ref _message, value);
    }

    public void ConnectionChanged()
    {
        if (_client() is null)
        {
            _previews.Clear();
            _episodes = [];
            _episode = null;
            ApplyReview(null);
            RaisePropertyChanged(nameof(Episodes));
            RaisePropertyChanged(nameof(Episode));
        }
        UpdateCommands();
        QueueRefresh();
    }

    public async void QueueRefresh()
    {
        if (!IsActive || _client() is null)
        {
            return;
        }
        _refreshPending = true;
        if (_refreshing)
        {
            return;
        }
        _refreshing = true;
        try
        {
            while (_refreshPending && IsActive && _client() is not null)
            {
                _refreshPending = false;
                await Task.Delay(200);
                await RefreshAsync();
            }
        }
        catch (OperationCanceledException)
        {
            // 连接切换后由新会话发起刷新。
        }
        catch (Exception exception)
        {
            ReportError(exception);
        }
        finally
        {
            _refreshing = false;
            if (_refreshPending && IsActive)
            {
                QueueRefresh();
            }
        }
    }

    public async Task RefreshAsync()
    {
        var client = _client();
        if (client is null)
        {
            return;
        }
        var token = _token();
        var episodes = await client.GetEpisodesAsync(token);
        if (token.IsCancellationRequested || !ReferenceEquals(client, _client()))
        {
            return;
        }
        ReplaceEpisodes(episodes);
        var episodeId = Episode?.EpisodeId;
        if (episodeId is null)
        {
            Message = "暂无剧集。请先导入 episode.yaml。";
            return;
        }
        var review = await client.GetEpisodeReviewAsync(episodeId, token);
        if (Episode?.EpisodeId == episodeId && ReferenceEquals(client, _client()))
        {
            ApplyReview(review);
        }
    }

    private void ReplaceEpisodes(EpisodeSummary[] episodes)
    {
        if (_episodes.SequenceEqual(episodes))
        {
            return;
        }
        var previousId = _episode?.EpisodeId;
        var selection = episodes.FirstOrDefault(x => x.EpisodeId == previousId)
            ?? episodes.FirstOrDefault();
        _episodes = episodes;
        RaisePropertyChanged(nameof(Episodes));
        if (previousId != selection?.EpisodeId)
        {
            ApplyReview(null);
        }
        _episode = selection;
        RaisePropertyChanged(nameof(Episode));
    }

    private void ApplyReview(EpisodeReview? review)
    {
        var previousShotId = _shot?.ShotId;
        _canAssemble = review?.CanAssemble == true;
        _shots = review?.Shots ?? [];
        var selection = _shots.FirstOrDefault(x => x.ShotId == previousShotId)
            ?? _shots.FirstOrDefault();
        RaisePropertyChanged(nameof(Shots));
        _shot = selection;
        RaisePropertyChanged(nameof(Shot));
        SetCandidates();
        UpdateCommands();
    }

    private void SetCandidates()
    {
        var candidateId = _candidate?.Record.ArtifactId;
        var previousMacNote = _candidate?.Record.Note ?? "";
        var note = _note;
        _candidates = _shot?.Candidates.Select(record => new CandidateViewModel(record)).ToArray() ?? [];
        var selection = _candidates.FirstOrDefault(x => x.Record.ArtifactId == candidateId)
            ?? _candidates.FirstOrDefault();
        RaisePropertyChanged(nameof(Candidates));
        Candidate = selection;
        if (selection is not null && selection.Record.ArtifactId == candidateId)
        {
            if (note == previousMacNote || note == selection.Record.Note)
            {
                Note = selection.Record.Note;
                HasNoteConflict = false;
            }
            else if (previousMacNote != selection.Record.Note)
            {
                HasNoteConflict = true;
            }
        }
        _ = LoadPreviewsAsync(_candidates);
    }

    private async Task LoadPreviewsAsync(CandidateViewModel[] candidates)
    {
        var client = _client();
        var token = _token();
        foreach (var candidate in candidates)
        {
            if (token.IsCancellationRequested || !ReferenceEquals(candidates, _candidates))
            {
                return;
            }
            var record = candidate.Record;
            var cacheKey = record.ThumbnailId ?? record.ArtifactId;
            if (!_previews.TryGetValue(cacheKey, out var bitmap))
            {
                try
                {
                    if (record.ThumbnailId is { } id && client is not null)
                    {
                        var preview = await client.GetThumbnailAsync(record.TaskId, id, token);
                        bitmap = DecodeBitmap(new MemoryStream(Convert.FromBase64String(preview.JpegBase64)));
                    }
                    else if (record.Kind == "image" && IsLocalPath(record.Path) && File.Exists(record.Path))
                    {
                        bitmap = await Task.Run(() => DecodeBitmap(File.OpenRead(record.Path)), token);
                    }
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (Exception exception) when (exception is ApiException or FormatException
                    or IOException or NotSupportedException or UnauthorizedAccessException)
                {
                    // 单个缩略图故障时仍允许审片和播放本地文件。
                }
                if (bitmap is not null && ReferenceEquals(client, _client()))
                {
                    if (_previews.Count >= 64)
                    {
                        _previews.Clear();
                    }
                    _previews[cacheKey] = bitmap;
                }
            }
            candidate.Preview = bitmap;
            if (client is not null && candidate.ReportTask is { } task && candidate.ReportId is { } reportId)
            {
                try
                {
                    if (!_previews.TryGetValue(reportId, out var report))
                    {
                        var result = await client.GetThumbnailAsync(task, reportId, token);
                        report = DecodeBitmap(new MemoryStream(Convert.FromBase64String(result.JpegBase64)));
                        if (_previews.Count >= 64) _previews.Clear();
                        _previews[reportId] = report;
                    }
                    candidate.Report = report;
                }
                catch (OperationCanceledException) { return; }
                catch (Exception ex) when (ex is ApiException or IOException or FormatException or NotSupportedException)
                {
                    // Keep the score and failures visible if the report image is unavailable.
                }
            }
        }
    }

    private static BitmapImage DecodeBitmap(Stream stream)
    {
        using (stream)
        {
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.StreamSource = stream;
            bitmap.DecodePixelWidth = 340;
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.EndInit();
            bitmap.Freeze();
            return bitmap;
        }
    }

    private bool CanDecide() => !_saving && !HasNoteConflict && Candidate is not null && _client() is not null;

    private async Task DecideAsync(string decision)
    {
        if (_client() is not { } client || Candidate is not { } selected)
        {
            return;
        }
        _saving = true;
        UpdateCommands();
        try
        {
            await client.DecideArtifactAsync(selected.Record.ArtifactId, new(decision, Note, decision == "pick" && selected.IsManualGate), _token());
            Message = decision switch
            {
                "pick" when selected.IsManualGate => "已记录人工选用。所需素材全部确认后将放行下游任务。",
                "pick" => "已记录选用。",
                "redo" when selected.Record.TaskType == "review.imported" => "已标记这条历史素材需要重做。",
                "redo" => "已加入重做队列。",
                _ => "已记录不要。",
            };
            await RefreshAsync();
        }
        finally
        {
            _saving = false;
            UpdateCommands();
        }
    }

    private async Task AssembleAsync()
    {
        if (_client() is not { } client || Episode is not { } episode)
        {
            return;
        }
        _saving = true;
        UpdateCommands();
        try
        {
            await client.AssembleEpisodeAsync(episode.EpisodeId, _token());
            Message = "本集合成任务已入队。";
        }
        finally
        {
            _saving = false;
            UpdateCommands();
        }
    }

    private Task PlayAsync()
    {
        var path = Candidate?.Record.Path;
        if (path is null || !IsLocalPath(path) || !File.Exists(path))
        {
            throw new InvalidOperationException("找不到本机视频文件。");
        }
        using var player = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        return Task.CompletedTask;
    }

    private void UpdateCommands()
    {
        RaisePropertyChanged(nameof(CanOpenBatch));
        RaisePropertyChanged(nameof(HasConnection));
        RefreshCommand.NotifyCanExecuteChanged();
        SyncApprovedFramesCommand.NotifyCanExecuteChanged();
        PickCommand.NotifyCanExecuteChanged();
        RedoCommand.NotifyCanExecuteChanged();
        RejectCommand.NotifyCanExecuteChanged();
        PlayCommand.NotifyCanExecuteChanged();
        AssembleCommand.NotifyCanExecuteChanged();
    }

    private void ReportError(Exception exception)
    {
        if (exception is not OperationCanceledException)
        {
            Message = $"操作失败：{exception.Message}";
        }
    }

    internal static bool IsLocalPath(string path) =>
        path.Length >= 3 && char.IsAsciiLetter(path[0]) && path[1] == ':'
        && (path[2] == '\\' || path[2] == '/') && Path.IsPathFullyQualified(path);

    internal static string FormatQc(JsonElement qc) =>
        qc.ValueKind == JsonValueKind.Object && qc.EnumerateObject().Any()
            ? JsonNode.Parse(qc.GetRawText())!.ToJsonString(QcFormat)
            : "暂无质检报告。";
}

public sealed class CandidateViewModel(ReviewCandidate record) : ObservableObject
{
    private BitmapSource? _preview;
    public ReviewCandidate Record { get; } = record;
    public BitmapSource? Preview
    {
        get => _preview;
        set => SetProperty(ref _preview, value);
    }

    public string KindName => Record.Kind switch
    {
        "video" => "视频",
        "audio" => "音频",
        _ => "图片",
    };

    public string Title => $"{KindName} · 第 {Record.Take} 条";
    public string FileName => Path.GetFileName(Record.Path);
    public string Origin => string.Join(" · ", new[] {
        Record.Seed is { } seed ? $"种子 {seed}" : null, Record.SourceId,
    }.Where(x => !string.IsNullOrEmpty(x)));
    public string DecisionName => Record.Decision switch
    {
        "pick" => "已选用",
        "redo" => "已标记重做",
        "reject" => "不要",
        _ => "待审",
    };
    private string? QcString(string key) =>
        Record.Qc.ValueKind == JsonValueKind.Object && Record.Qc.TryGetProperty(key, out var value)
            && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    public bool IsManualGate => QcString("gate_status") == "QC_MANUAL_REVIEW";
    private bool QcFlag(string key) => Record.Qc.ValueKind == JsonValueKind.Object &&
        Record.Qc.TryGetProperty(key, out var flag) && flag.ValueKind == JsonValueKind.True;
    public bool CanPick => QcString("gate_status") is null or "Completed" || QcFlag("can_confirm");
    public bool CanRedo => CanPick || QcFlag("can_redo");
    internal string? ReportTask => QcString("report_task_id");
    internal string? ReportId => QcString("report_thumbnail_id");
    private BitmapSource? _report;
    public BitmapSource? Report { get => _report; set => SetProperty(ref _report, value); }
    public string QcText
    {
        get
        {
            var qc = Record.Qc;
            if (qc.ValueKind == JsonValueKind.Object && qc.TryGetProperty("score", out var score)
                && qc.TryGetProperty("fails", out var fails) && fails.ValueKind == JsonValueKind.Array)
            {
                var failures = fails.EnumerateArray().Select(x => x.ToString()).ToArray();
                var issues = failures.Length > 0 ? string.Join(Environment.NewLine, failures) : "无";
                var review = IsManualGate ? (QcFlag("human_released") ?
                    (QcFlag("human_confirmed") ? "人工复核已放行" : "人工已选用其他候选") :
                    QcFlag("human_confirmed") ? "已人工确认，等待其余素材" : "待人工复核") + Environment.NewLine : "";
                return $"{review}得分 {score}{Environment.NewLine}未通过项：{issues}";
            }
            return QcString("gate_status") switch
            {
                "Queued" => "已排队等待质检。",
                "Running" => "正在质检。",
                "EXECUTOR_FAILED" => "质检执行失败。",
                _ => ProductionViewModel.FormatQc(qc),
            };
        }
    }
    public bool CanPlay => Record.Kind == "video" && ProductionViewModel.IsLocalPath(Record.Path)
        && Path.GetExtension(Record.Path).ToLowerInvariant() is ".mp4" or ".m4v" or ".mov" or ".mkv" or ".webm";
}
