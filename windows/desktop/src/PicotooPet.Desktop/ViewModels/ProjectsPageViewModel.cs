using PicotooPet.Desktop.Core.Contracts;
using PicotooPet.Desktop.Services;

namespace PicotooPet.Desktop.ViewModels;

/// <summary>真实项目目录；只管理项目元数据，不扫描工作目录。</summary>
public sealed class ProjectsPageViewModel : PageViewModel
{
    private readonly ControlCenterSession? _session;
    private IReadOnlyList<ProjectRecord> _projects = Array.Empty<ProjectRecord>();
    private ProjectRecord? _selectedProject;
    private string _newTitle = "新项目";
    private string _newProjectType = "automation";
    private string _newSourceApp = "PicotooPet";
    private string _statusMessage = "项目来自 Mac Core SQLite 事实源。";
    private bool _isBusy;

    public ProjectsPageViewModel(ControlCenterSession session) : base("项目")
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    private ProjectsPageViewModel(IReadOnlyList<ProjectRecord> projects) : base("项目")
    {
        Projects = projects;
        SelectedProject = projects.Count > 0 ? projects[0] : null;
    }

    public IReadOnlyList<ProjectRecord> Projects
    {
        get => _projects;
        private set => SetProperty(ref _projects, value);
    }

    public ProjectRecord? SelectedProject
    {
        get => _selectedProject;
        set
        {
            if (SetProperty(ref _selectedProject, value))
            {
                RaisePropertyChanged(nameof(CanArchive));
            }
        }
    }

    public string NewTitle
    {
        get => _newTitle;
        set => SetProperty(ref _newTitle, value);
    }

    public string NewProjectType
    {
        get => _newProjectType;
        set => SetProperty(ref _newProjectType, value);
    }

    public string NewSourceApp
    {
        get => _newSourceApp;
        set => SetProperty(ref _newSourceApp, value);
    }

    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetProperty(ref _statusMessage, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RaisePropertyChanged(nameof(CanArchive));
            }
        }
    }

    public bool CanArchive => !IsBusy && SelectedProject is { Status: not "Archived" };

    public static ProjectsPageViewModel CreateForSmokeTest(IReadOnlyList<ProjectRecord> projects) =>
        new(projects);

    public async Task RefreshAsync(CancellationToken cancellationToken)
    {
        var session = RequireSession();
        IsBusy = true;
        try
        {
            Projects = await session.GetProjectsAsync(cancellationToken).ConfigureAwait(false);
            SelectedProject = Projects.FirstOrDefault(item => item.ProjectId == SelectedProject?.ProjectId)
                ?? (Projects.Count > 0 ? Projects[0] : null);
            StatusMessage = Projects.Count == 0 ? "当前没有项目。" : $"已加载 {Projects.Count} 个项目。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task CreateAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(NewTitle)
            || string.IsNullOrWhiteSpace(NewProjectType)
            || string.IsNullOrWhiteSpace(NewSourceApp))
        {
            throw new InvalidOperationException("项目标题、类型和来源不能为空。");
        }
        var session = RequireSession();
        IsBusy = true;
        try
        {
            var created = await session.CreateProjectAsync(
                new ProjectCreateRequest(
                    NewTitle.Trim(),
                    NewProjectType.Trim(),
                    NewSourceApp.Trim()),
                cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            SelectedProject = Projects.FirstOrDefault(item => item.ProjectId == created.ProjectId);
            StatusMessage = $"项目“{created.Title}”已创建。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task ArchiveSelectedAsync(CancellationToken cancellationToken)
    {
        var selected = SelectedProject ?? throw new InvalidOperationException("请先选择项目。");
        var session = RequireSession();
        IsBusy = true;
        try
        {
            await session.ArchiveProjectAsync(selected.ProjectId, cancellationToken).ConfigureAwait(false);
            await RefreshCoreAsync(session, cancellationToken).ConfigureAwait(false);
            SelectedProject = Projects.FirstOrDefault(item => item.ProjectId == selected.ProjectId);
            StatusMessage = $"项目“{selected.Title}”已归档。";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RefreshCoreAsync(ControlCenterSession session, CancellationToken cancellationToken)
    {
        Projects = await session.GetProjectsAsync(cancellationToken).ConfigureAwait(false);
    }

    private ControlCenterSession RequireSession() =>
        _session ?? throw new InvalidOperationException("Smoke test 模式不能访问网络。");
}
