# Phase 10D-C 受控本地 Commit Candidate 设计

- 产品版本：`2.3.15.1`
- 基线产品版本：`2.3.14.1`
- 基线源码提交：`3c2e741ffd69fef1fa12076467a61ab24c1c2286`
- 基线 Draft PR：`#15`
- 里程碑：Phase 10D-C
- 状态：Approved direction by standing user instruction; non-high-risk implementation proceeds without approval pauses

## 1. 目标

`2.3.14.1` 已完成：

`Codex Session -> bounded Return -> 人工 Review -> Adoption Candidate -> adoption_ready`

但 `adoption_ready` 只证明 normalized change set 能从 exact base 确定性重放并通过固定本地静态验证，不会形成 Git 提交。

`2.3.15.1` 补齐下一段闭环：

1. 只有 `adoption_ready` 的 Adoption Candidate 才能进入 Commit Candidate 流程；
2. Windows 原生 WPF 显示固定提交摘要与 provenance，用户不能编辑 commit message、author、ref、路径或命令；
3. 用户必须对“创建本地 Git 提交对象”进行一次新的、digest-bound 明确批准；
4. Mac Core 作为唯一事实源持久化批准和 Commit Candidate 状态；
5. Mac Worker 在 fresh isolated worktree 中再次从 immutable `base_commit` 重放同一 change set 并固定验证；
6. Worker 使用 Git plumbing + 临时 index 构造提交，不执行 repository Git hooks，不执行 clean/smudge filters，不调用 Provider，不访问网络；
7. 成功后生成一个只有本机可见的 Git commit object，并用固定 namespaced ref 保活；
8. 成功状态为 `commit_ready`；
9. 本版仍然不自动创建普通 branch、不 push、不创建 PR、不 merge、不 tag、不 release。

本版目标是“把已人工接受且可重放的 Adoption Candidate 变成可追溯、可引用、但仍留在本机的 Git 提交候选”。

## 2. 版本规则与已验证 Mac hotfix

- 用户规则：没有实际产品功能更新的维护修复用 `2.3.14.2`；新增实际功能才使用 `2.3.15.1`。
- 本版新增 Commit Candidate 功能，因此版本固定为 `2.3.15.1`。
- 已在真实 Mac 环境通过验证的 MacCore hotfix1 / MacWorker hotfix2 **不单独重做一轮人工验证，也不单独发布 2.3.14.2**。
- 这些 hotfix 被视为 2.3.15.1 的“不得回归已接受基线”。若源码审计发现正式 `2.3.14.1` branch 尚未包含其中某一运行时修复，则只同步维持已验收行为所需的最小源码 delta，并由 2.3.15.1 自己的正常原生 CI/实机验收覆盖，不另立 hotfix 验收项目。
- 不为了补证据自动运行真实 Codex Session；CI 继续使用 deterministic fake Codex/fixture。

## 3. 方案选择

### 3.1 采用：Git plumbing + namespaced local ref

不使用普通 `git commit`，也不直接创建 `refs/heads/*` 分支。

Worker 在 validated replay 之后：

1. 使用临时 `GIT_INDEX_FILE`；
2. `git read-tree <base_commit>` 初始化 exact base tree；
3. add/modify payload 使用 `git hash-object --no-filters -w --stdin` 写 blob；
4. 使用 `git update-index --cacheinfo` 更新对应路径；
5. delete 使用 index 删除；
6. `git write-tree` 得到 candidate tree；
7. 独立核验 `git diff-tree` 与 normalized change set 完全一致；
8. `git commit-tree <tree> -p <base_commit>` 生成 commit object；
9. 通过 compare-and-swap 方式写固定 ref：`refs/picotoopet/commit-candidates/<candidate_id>`；
10. 清理临时 index/worktree。

这样能避免 repository hook、普通 branch 污染以及 clean/smudge filter 执行，并保证 commit object 在 worktree 清理后仍由 ref 保活。

### 3.2 不采用：普通 `git commit`

普通 commit 可能触发仓库 hook，且依赖工作树/index/branch 当前状态，攻击面和不确定性更大。

### 3.3 不采用：直接创建 branch + push/Draft PR

会在一个版本内同时跨越本地 Git、远端写入和 PR 权限三个安全边界；Phase 10D-C 只解决本地可追溯提交，远端能力留给后续独立版本。

## 4. 不可突破的边界

- `main` 不修改；PR 保持 Draft、stacked、未合并。
- Windows/Mac 用户机器只安装预编译产品包，不编译 PicotooPet 源码。
- Mac Core + SQLite 仍是 Commit Candidate 状态唯一事实源。
- 只允许从现有 `adoption_ready` Candidate 创建 Commit Candidate。
- base commit、change-set digest、candidate id、commit message、author、ref 全部由服务端固定生成；API/Windows 不接收这些自由输入。
- 不允许 arbitrary command、shell、patch、path、model、env、commit message、author/email、branch name、remote name、URL 输入。
- 不运行 Git hooks；不运行 clean/smudge filters；不调用 Codex 或其他 Provider；不访问网络。
- commit 的唯一 parent 必须是 Adoption Candidate 的 immutable `base_commit`。
- commit tree 相对 base 的 diff 必须与 normalized change set 路径、operation 和结果 SHA-256 一致。
- namespaced ref 固定在 `refs/picotoopet/commit-candidates/`，禁止写 `refs/heads/`、`refs/tags/`、`refs/remotes/`。
- 不自动 push、PR、merge、tag、release。

## 5. 固定 Commit Identity 与 Message

为避免依赖用户 Git 配置和自由输入，Commit Candidate 使用固定本地 provenance identity：

- author/committer name：`PicotooPet Local Adoption`
- author/committer email：`picotoopet@localhost`
- 时间：Worker 开始提交阶段时的 UTC 时间，写入安全事实；不承诺 commit SHA 跨时间重跑确定性一致。

commit message 由服务端固定构造，例如：

`PicotooPet adoption candidate <candidate_id>`

并固定附带 trailers：

- `PicotooPet-Adoption-Candidate: <candidate_id>`
- `PicotooPet-Return: <return_id>`
- `PicotooPet-Session: <session_id>`
- `PicotooPet-Base-Commit: <base_commit>`
- `PicotooPet-Change-Set-SHA256: <digest>`

不得包含用户 prompt、transcript、diff 正文、Token、绝对路径或其他 secret-bearing 内容。

## 6. 持久化与 migration 8

新增 SQLite 表 `provider_commit_candidates`，至少包含：

- `commit_candidate_id` primary key
- `adoption_candidate_id` unique
- `session_id`
- `return_id`
- `status`
- `base_commit`
- `change_set_digest`
- `tree_sha`
- `commit_sha`
- `local_ref`
- `approval_id`
- `idempotency_key` unique
- `validation_json`
- `failure_code`
- `author_time_utc`
- `created_at`
- `updated_at`
- `finished_at`
- `preview_json`

migration 必须 additive、幂等，保留历史 task/result/Handoff/Return/Provider/Adoption 数据。

## 7. 状态机

Commit Candidate：

`requested -> waiting_approval -> queued -> staging -> replaying -> validating -> committing -> commit_ready`

终态：

- `rejected`
- `cancelled`
- `artifact_invalid`
- `base_mismatch`
- `policy_blocked`
- `validation_failed`
- `commit_failed`
- `ref_conflict`
- `failed`

固定错误码至少包括：

- `COMMIT_ADOPTION_NOT_READY`
- `COMMIT_ALREADY_REQUESTED`
- `COMMIT_APPROVAL_REJECTED`
- `COMMIT_ARTIFACT_INVALID`
- `COMMIT_BASE_MISMATCH`
- `COMMIT_PATH_POLICY`
- `COMMIT_TREE_MISMATCH`
- `COMMIT_HOOK_POLICY`
- `COMMIT_REF_CONFLICT`
- `COMMIT_OBJECT_FAILED`
- `COMMIT_WORKTREE_CLEANUP_FAILED`

错误响应不得回显文件正文、diff 正文、绝对路径、命令、Token 或 transcript。

## 8. Approval 与 API

使用现有 Approval Center 创建新 approval kind：

`provider.commit.create-v1`

approval digest 必须绑定：

- `commit_candidate_id`
- `adoption_candidate_id`
- `session_id`
- `return_id`
- `base_commit`
- `change_set_digest`
- fixed local ref
- fixed message digest

新增固定 API：

- `POST /api/v1/provider-adoption-candidates/{candidate_id}/commit/prepare`
- `GET /api/v1/provider-commit-candidates?limit=100`
- `GET /api/v1/provider-commit-candidates/{commit_candidate_id}`

prepare 为 bodyless + `Idempotency-Key`，只创建 Commit Candidate + digest-bound approval，不直接执行 Git 写入。

Approval Center 的既有 approve/reject API 继续负责明确批准。只有批准后 Core 才排入固定 Worker 任务。

## 9. Worker 固定任务

新增任务类型：

`provider.commit.create-v1`

Core 生成的 Worker payload 只包含 server-owned IDs/digests，不包含自由路径、命令、commit message 或 ref。

Worker 固定步骤：

1. 重新读取 Commit Candidate 与对应 Adoption Candidate；
2. 要求 approval 已通过且 digest 完全匹配；
3. 创建新的 isolated worktree，checkout exact base commit；
4. 重新验证 ProviderReturnArtifactStore manifest/change-set/payload；
5. 用 Python 文件 I/O 重放 add/modify/delete；
6. 重跑 2.3.14.1 固定 replay validation；
7. 校验 worktree diff 与 normalized change set 完全一致；
8. 使用临时 index + Git plumbing 构造 candidate tree；
9. 禁止 hooks/filters，验证 tree diff 与已验证 worktree diff 一致；
10. `commit-tree` 生成唯一 parent=`base_commit` 的 commit object；
11. 固定 namespaced ref CAS 写入；
12. 回读 commit/tree/parent/ref，独立核验 provenance；
13. 状态写为 `commit_ready`；
14. 无论成功失败都清理 worktree 和临时 index。

如果 commit object 已生成但 ref 写入失败，该 object 允许成为 dangling object，但状态必须失败且不得伪报 `commit_ready`。

## 10. Windows WPF

在现有 Cloud Development / Return Review 区域增加“本地提交候选”区域：

- 只对 `adoption_ready` 显示“准备本地提交”动作；
- 显示 Adoption Candidate ID、base commit、change-set digest、changed file count；
- 显示固定 commit message preview；
- 点击准备后显示新的 Approval ID 和 waiting_approval 状态；
- 批准后显示 queued/staging/replaying/validating/committing/commit_ready；
- `commit_ready` 显示 commit SHA、tree SHA、parent/base SHA、fixed local ref、完成时间；
- UI 明示：`commit_ready != pushed != PR-ready != merge-ready`；
- 不增加 commit message TextBox、branch 输入、remote 输入、push 按钮、PR 按钮、terminal、WebView；
- ItemsSource 刷新按 ID 保留选择/预览；网络错误保留已有安全预览；
- 真实 STA WPF 测试执行 DataBind、Measure、Arrange、UpdateLayout。

## 11. TDD

必须先 RED 后 GREEN，至少覆盖：

1. migration 8 additive/idempotent；
2. 非 `adoption_ready` 不可 prepare；
3. prepare bodyless、幂等且不接受 message/ref/path/body；
4. approval digest 绑定全部关键字段，批准前不得创建 Git object/ref；
5. 同一 Adoption Candidate 最多一个 Commit Candidate；
6. fixed ref 必须位于 `refs/picotoopet/commit-candidates/`；
7. malicious `.git/hooks/*` witness 不得被执行；
8. malicious `.gitattributes` clean/smudge filter witness 不得被执行；
9. commit 唯一 parent 等于 exact base commit；
10. commit tree diff 与 normalized change set 完全一致；
11. add/modify/delete 与文件 mode 策略正确；add 固定 `100644`，modify 保留 base regular-file mode，link/submodule/device 一律拒绝；
12. ref CAS 冲突不得覆盖已有不同 commit；
13. duplicate/retry 保持同一事实记录，不产生第二个受支持 ref；
14. 失败路径不写普通 branch/tag/remote ref；
15. 成功和失败都清理临时 index/worktree；
16. `commit_ready` 不触发 network、push、PR、merge、tag、release；
17. Windows WPF commit candidate 布局、approval 状态和刷新保持；
18. 历史 Task Center、Handoff、Return、Provider Session、Adoption Candidate 全量回归；
19. 已通过实机验证的 Mac Core/Worker 启动与 Codex 可执行定位行为作为非回归合同继续保持，但不单独重跑旧 hotfix 人工验收。

## 12. CI 与影响范围

本版预计实际修改：

- Windows WPF / typed client：受影响；
- Mac Core API/SQLite/approval/state：受影响；
- Mac Worker：新增 commit handler，受影响。

因此 `2.3.15.1` 必须跑当前 exact-head 的：

1. Windows Control Center native WPF CI；
2. Windows Prebuilt Release；
3. Mac Core arm64 native CI；
4. Mac Worker arm64 native CI。

CI 使用 fixture adoption artifact，不调用真实 Codex、不消费用户额度、不访问 GitHub remote。

未来版本若 Worker 未变，继续使用 impact detection 跳过 Worker 重复打包。

## 13. 版本升级与发布完整性

首次版本提交前执行 repository-wide stale version literal audit；把所有活动版本面、fixtures、assertions、installer/package metadata 原子升级到 `2.3.15.1`。

正式交付必须基于同一 exact source head，且下载后独立复核：

- product version；
- source/build provenance；
- archive traversal/link safety；
- Manifest coverage；
- payload size + SHA-256；
- Windows PE / Mac arm64；
- no user-side source build；
- required native gate terminal success。

不得把早期错误版本制品改名后冒充 `2.3.15.1`。

## 14. 安装包与人工验收规则

非高风险执行不中途停，持续到必要安装包真正生成或遇到明确外部硬阻塞。

本版本三个运行时组件均预计受影响，因此正常完成时一次性交付：

- Windows win-x64 预编译安装包；
- Mac Core arm64 离线安装包；
- Mac Worker arm64 离线安装包；
- 各自 SHA-256。

不额外生成用户侧独立 verifier 程序。

最终同时提供人工验收标准，至少验证：

1. Windows/Mac 冷启动与既有 2.3.14.1 功能不回归；
2. 已有 `adoption_ready` Candidate 能发起 Commit Candidate；
3. 未批准前 Mac Git repo 不出现 candidate ref；
4. 批准后进入 `commit_ready`；
5. commit parent/base、tree、change-set provenance 一致；
6. 本机只有 `refs/picotoopet/commit-candidates/<id>`，没有自动普通 branch；
7. GitHub 上没有自动 push、Draft PR、merge、tag 或 release；
8. 现有 Mac Core/Worker/Codex launchd 执行行为保持已验收状态。

## 15. 非目标

- 自动 push；
- 自动创建 GitHub Draft PR；
- 自动 merge；
- tag/release；
- 任意 commit message/author/ref 输入；
- arbitrary shell/command；
- Provider 二次调用；
- 真实 Usage/额度读取；
- binary/symlink/submodule adoption；
- 把 `commit_ready` 宣称为 PR-ready 或 merge-ready。
