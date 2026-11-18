using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Encodings.Web;
using System.Windows.Media.Imaging;
using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Core.Networking;

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
    private string _note = "";
    private string _message = "";
    private readonly Dictionary<string, BitmapSource> _previews = new(StringComparer.Ordinal);

    public ProductionViewModel(Func<MacCoreClient?> client, Func<CancellationToken> token)
    {
        _client = client;
        _token = token;
        RefreshCommand = new AsyncRelayCommand(RefreshAsync, ReportError, () => _client() is not null);
        PickCommand = new AsyncRelayCommand(() => DecideAsync("pick"), ReportError, CanDecide);
        RedoCommand = new AsyncRelayCommand(() => DecideAsync("redo"), ReportError, CanDecide);
        RejectCommand = new AsyncRelayCommand(() => DecideAsync("reject"), ReportError, CanDecide);
        AssembleCommand = new AsyncRelayCommand(
            AssembleAsync, ReportError, () => _canAssemble && !_saving && _client() is not null);
        PlayCommand = new AsyncRelayCommand(PlayAsync, ReportError, () => Candidate?.CanPlay == true);
    }

    public AsyncRelayCommand RefreshCommand { get; }
    public AsyncRelayCommand PickCommand { get; }
    public AsyncRelayCommand RedoCommand { get; }
    public AsyncRelayCommand RejectCommand { get; }
    public AsyncRelayCommand AssembleCommand { get; }
    public AsyncRelayCommand PlayCommand { get; }

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
                }
                RaisePropertyChanged(nameof(QcText));
                RaisePropertyChanged(nameof(CandidateHint));
                UpdateCommands();
            }
        }
    }

    public string QcText => Candidate?.QcText ?? "选择候选查看质检报告。";
    public string CandidateHint => Candidate?.CanPlay == true ? "视频文件将用本机播放器打开。" : "";

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
        var note = _note;
        _candidates = _shot?.Candidates.Select(record => new CandidateViewModel(record)).ToArray() ?? [];
        var selection = _candidates.FirstOrDefault(x => x.Record.ArtifactId == candidateId)
            ?? _candidates.FirstOrDefault();
        RaisePropertyChanged(nameof(Candidates));
        Candidate = selection;
        if (selection?.Record.ArtifactId == candidateId)
        {
            Note = note;
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

    private bool CanDecide() => !_saving && Candidate is not null && _client() is not null;

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
            await client.DecideArtifactAsync(selected.Record.ArtifactId, new(decision, Note), _token());
            Message = decision switch
            {
                "pick" => "已记录选用。",
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
        RefreshCommand.NotifyCanExecuteChanged();
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
    public string DecisionName => Record.Decision switch
    {
        "pick" => "已选用",
        "redo" => "已重做",
        "reject" => "不要",
        _ => "待审",
    };
    public string QcText => ProductionViewModel.FormatQc(Record.Qc);
    public bool CanPlay => Record.Kind == "video" && ProductionViewModel.IsLocalPath(Record.Path)
        && Path.GetExtension(Record.Path).ToLowerInvariant() is ".mp4" or ".mov" or ".mkv" or ".webm";
}
