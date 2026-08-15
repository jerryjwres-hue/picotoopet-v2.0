# PicotooPet Research Gateway 2.3.27.1 Design

## Goal

Ship a standalone macOS Research Gateway package that exposes stable `research.*` read capabilities to PicotooPet while keeping Agent Reach, OpenCLI, `gh`, `mcporter`, `yt-dlp`, `bili` and browser-session details outside Mac Core.

## Boundary

The gateway is an independent process-level capability plane. It is not installed into the Mac Core virtual environment and Mac Core does not import concrete platform adapters.

Flow:

`PicotooPet -> Capability Router -> Research Gateway -> Agent Reach/platform tools`

## Frozen read surface

- `research.search`
- `research.web.read`
- `research.social.search`
- `research.video.search`
- `research.video.transcript`
- `research.github.search`
- `research.community.search`
- `research.company.lookup`

The 2.3.27.1 gateway is read-only. Any write-shaped capability or action is rejected before subprocess execution. Future write support must pass through PicotooPet's shared Approval Gate and is explicitly out of scope for this release.

## Adapter isolation

Concrete commands are built only inside the gateway process. The public request contains a capability plus structured parameters; callers never supply arbitrary shell strings. Subprocess execution uses argv arrays with `shell=False` semantics and an injectable runner for deterministic tests.

## Backend routing

- General search: Exa through `mcporter`.
- Web read: Jina Reader through `curl`.
- Social/community: OpenCLI adapters.
- GitHub: `gh`.
- YouTube/video: `yt-dlp`; Bilibili search through `bili` where selected.
- Company lookup: LinkedIn MCP through `mcporter`.

Xiaoyuzhou is intentionally excluded.

## macOS installation

The release artifact is an architecture-labelled `.tar.gz` containing one-click `.command` install/verify/uninstall scripts, the gateway runtime, a version file, README, and a cryptographic manifest. External tools are installed at process level (`pipx`, Homebrew/npm tools) and remain separate from Mac Core.

The installer supports a CI fixture mode that installs only the gateway payload into an isolated HOME. Production mode installs/updates the required external tools and then runs health checks.

## Security invariants

1. Read-only capability allowlist.
2. No arbitrary command or shell execution input.
3. Bounded subprocess timeout.
4. Dedicated Chrome profile remains the browser-session boundary; installer does not export or copy cookies.
5. No Xiaoyuzhou/Whisper/ffmpeg dependency is introduced by this package.
6. Secrets and browser state are not embedded in artifacts or manifests.

## Acceptance

- Unit tests prove allowlist enforcement, argv-only dispatch and injectable execution.
- Contract tests prove package contents and process isolation.
- Native macOS CI builds and fixture-installs the artifact.
- Full Python regression, alignment verification and Python compilation remain green.
- GitHub Actions exposes a real downloadable Research Gateway artifact with SHA-256 evidence.
