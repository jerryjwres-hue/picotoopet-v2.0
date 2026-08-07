# Phase 10D-B 受控 Return 审阅与落地候选设计

- 产品版本：`2.3.14.1`
- 基线版本：`2.3.13.2`
- 基线提交：`0caeb2ef6031a6a004d6e80584783d9c5598e78d`
- 里程碑：Phase 10D-B
- 状态：Approved direction by standing user instruction; non-high-risk implementation proceeds without approval pauses

## 1. 目标

`2.3.13.2` 已把真实 Codex Session 安全推进到 `ready_for_review`，但 Provider worktree 在结束后会清理，Mac Core 只持久化安全事实，尚不能把经过人工审阅的 Return 形成可重复验证的落地候选。

`2.3.14.1` 补齐下一段闭环：

1. Mac Worker 在 Provider worktree 清理前生成一个**不可变、有界、可重放的 normalized change set**；
2. Mac Core 保存 change-set 元数据、文件 payload 和 review-safe diff 的独立 SHA-256，不把正文写进 SQLite；
3. Windows 原生 WPF 对 `ready_for_review` Session 显示变更路径、状态、大小、摘要和有界文本 diff；
4. 用户只能执行固定的“接受”或“拒绝”，不能编辑 patch、路径、命令、模型或环境变量；
5. 接受后 Mac Core 创建唯一 Adoption Candidate，并排入固定 Worker 任务；
6. Mac Worker 从同一 immutable `base_commit` 创建新的隔离 worktree，独立重放 normalized change set；
7. Worker 重验路径、文件哈希、base 文件哈希、symlink、文本编码和 change-set digest，并执行固定本地静态验证；
8. 验证成功进入 `adoption_ready`，失败进入固定终态并清理 worktree；
9. `adoption_ready` 仍然**不自动 commit、push、PR、merge、tag 或 release**。

本版目标是“人工审阅后形成可信落地候选”，不是自动发布。

## 2. 方案选择

### 2.1 采用：normalized change set + 新隔离 worktree 重放

不直接依赖 Provider 原 worktree，也不让 Windows 上传 patch。每个变更条目固定为 `add | modify | delete`，包含相对路径、结果 SHA-256、结果大小，以及 modify/delete 的 base 文件 SHA-256。新增/修改文本 payload 存在 Mac 本机应用数据目录中，单文件仍受 64 KiB、总 Return 256 KiB、最多 5 文件限制。

优点：base commit 不变时可确定性重放；不需要 shell patch 解析；Windows 不能篡改内容；Provider 原 worktree 可以继续强制清理。

### 2.2 不采用：保留 Provider worktree 等用户决定

会让长期残留 worktree、进程恢复、磁盘清理和状态恢复复杂化，破坏 2.3.13.2 的强制清理边界。

### 2.3 不采用：Windows 直接下载/编辑/上传 patch

会把任意文件、路径和正文重新引入控制面，扩大攻击面并破坏 Mac Core 唯一事实源。

## 3. 不可突破的边界

- `main` 不修改；PR 保持 Draft、stacked、未合并。
- Windows/Mac 用户机器安装预编译包，不编译 PicotooPet 源码。
- Mac Core + SQLite 仍是 review/adoption 状态唯一事实源。
- change-set payload 仅保存在 Mac 本机受控运行目录；SQLite 只存 digest、路径、状态、大小和安全摘要。
- Windows 不接收 Codex 凭据、Keychain、Usage 页面、原始 transcript 或任意环境变量。
- 只接受 `ready_for_review`、`provider=codex`、存在 validated Return 的 Session。
- 只允许最多 5 个文本文件；单文件最大 64 KiB；change-set 总 payload 最大 256 KiB；review diff 最大 128 KiB。
- binary、symlink、hardlink、device、路径逃逸、绝对路径、盘符、NUL、Protected、Raw Evidence、secret pattern 一律拒绝。
- 用户不能编辑 diff、change set、base commit、测试命令或目标路径。
- 每个 Provider Session 最多一个 Review Decision；每个 accepted Session 最多一个 Adoption Candidate。
- 不自动 commit、push、PR、merge、tag、release；不自动购买 credits；不再次调用 Codex。

## 4. 持久化与 migration 7

新增 SQLite 表：

### `provider_return_artifacts`

安全事实字段至少包含：

- `return_id`
- `session_id`
- `handoff_id`
- `base_commit`
- `change_set_digest`
- `review_diff_digest`
- `changed_file_count`
- `payload_bytes`
- `artifact_status`
- `created_at`
- `preview_json`

不保存文件正文或 diff 正文。

### `provider_review_decisions`

- `decision_id`
- `session_id` unique
- `return_id`
- `decision` = `accepted | rejected`
- `change_set_digest`
- `idempotency_key` unique
- `created_at`
- `preview_json`

### `provider_adoption_candidates`

- `candidate_id`
- `session_id` unique
- `return_id`
- `status`
- `base_commit`
- `change_set_digest`
- `changed_file_count`
- `validation_json`
- `failure_code`
- `idempotency_key` unique
- `created_at`
- `updated_at`
- `finished_at`
- `preview_json`

migration 必须 additive、幂等，并保留所有历史 Handoff、Return、Broker、Provider Session 数据。

## 5. Artifact Store

新增 `ProviderReturnArtifactStore`，根目录由 `RuntimePaths` 服务端推导，例如 `runtime/provider-returns/<return_id>/`，Windows/API 永远不能提交该路径。

每个 artifact 固定包含：

- `change-set.json`
- `review.diff`
- `payload/<index>.txt`（仅 add/modify）
- `manifest.sha256`

`change-set.json` 每条记录：

- `operation`: `add | modify | delete`
- `path`: normalized POSIX relative path
- `base_sha256`: modify/delete 必填，add 必须为空
- `result_sha256`: add/modify 必填，delete 必须为空
- `size_bytes`: add/modify 的结果大小，delete 为 0
- `payload_name`: add/modify 对应固定 payload 文件名，delete 为空

写入使用临时目录 + fsync/rename 风格原子切换；读取时重新验证 manifest、digest、大小和路径。

## 6. Provider Return 收口变化

Phase 10D-A Worker 在 cleanup 前：

1. 读取 Git 变更状态；
2. 对每个允许路径计算 base/result 哈希；
3. 拒绝 binary、link、超限和 secret；
4. 构造 normalized change set；
5. 生成只读 review diff；
6. 写入 Artifact Store；
7. Mac Core 写入 `provider_return_artifacts` 安全事实；
8. Session 才能进入 `ready_for_review`；
9. 无论成功失败，Provider 原 worktree 仍强制 cleanup。

旧的 2.3.13.2 `ready_for_review` Session 若没有 artifact，Windows 显示“legacy/no-adoption-artifact”，只能查看历史，不能接受落地。

## 7. Review API

新增固定 API：

- `GET /api/v1/provider-sessions/{session_id}/review`
- `POST /api/v1/provider-sessions/{session_id}/review/accept`
- `POST /api/v1/provider-sessions/{session_id}/review/reject`
- `GET /api/v1/provider-adoption-candidates?limit=100`
- `GET /api/v1/provider-adoption-candidates/{candidate_id}`

accept/reject 都是 bodyless + `Idempotency-Key`；不接受 reason、patch、路径、命令或自由 JSON。

Review 安全投影允许返回：变更路径、operation、size、base/result digest、bounded review diff、artifact digest 和固定安全提示。diff 必须是 UTF-8 文本、最大 128 KiB、通过 secret/redaction 检查。

## 8. Adoption Worker

新增固定任务类型：

`provider.adoption.apply-v1`

Worker payload 只由 Mac Core 生成，包含 candidate/session/return IDs、immutable base commit、change-set digest；不包含用户命令或路径。

执行：

1. 创建新的 Session-independent adoption worktree；
2. 校验受信任仓库 clean 且不在 main/master；
3. checkout exact base commit；
4. Artifact Store 重新验证；
5. 对 modify/delete 校验 base 文件 SHA-256；
6. 以 Python 文件 I/O 重放 add/modify/delete，不使用 shell patch；
7. 重算结果 SHA-256 和 changed paths；
8. 执行固定静态验证：`git diff --check`、UTF-8 解码、`.py` 使用 `ast.parse`；不执行 Provider 自带脚本；
9. 生成 candidate digest 与安全验证摘要；
10. 状态变为 `adoption_ready`；
11. 无论成功失败都 cleanup adoption worktree。

`adoption_ready` 仅表示“change set 可从 exact base 确定性重放且通过本地静态验证”，不表示跨平台 CI 已通过或可合并。

## 9. Windows WPF

现有 Phase 10D-A Provider 面板扩展“人工审阅与落地候选”区域：

- 仅 `ready_for_review` Session 可进入审阅；
- 显示 Return ID、artifact digest、文件数；
- 列出最多 5 个 path/operation/size；
- 显示最大 128 KiB 的只读 diff；
- 固定按钮：“接受并创建落地候选”“拒绝此 Return”“刷新候选状态”；
- 显示 adoption candidate 状态、validation summary 和 failure code；
- review/adoption ItemsSource 刷新时按 ID 保留选择与预览；
- 网络错误保留已有安全预览；
- 真实 STA WPF 测试执行 DataBind、Measure、Arrange、UpdateLayout。

禁止新增：TextBox patch 编辑、文件选择器、终端、WebView、命令框、模型框、路径框、自动发布按钮。

## 10. 状态与错误

Review：`unavailable | reviewable | accepted | rejected | legacy_no_artifact`。

Adoption Candidate：

`queued -> staging -> applying -> validating -> adoption_ready`

终态：

`rejected | cancelled | artifact_invalid | base_mismatch | policy_blocked | validation_failed | failed`

固定错误码至少包括：

- `ADOPTION_SESSION_NOT_REVIEWABLE`
- `ADOPTION_ARTIFACT_MISSING`
- `ADOPTION_ARTIFACT_INVALID`
- `ADOPTION_ALREADY_DECIDED`
- `ADOPTION_ALREADY_CREATED`
- `ADOPTION_BASE_MISMATCH`
- `ADOPTION_PATH_POLICY`
- `ADOPTION_SECRET_REJECTED`
- `ADOPTION_BINARY_REJECTED`
- `ADOPTION_VALIDATION_FAILED`
- `ADOPTION_WORKTREE_CLEANUP_FAILED`

错误响应不得回显 diff 正文、文件正文、绝对路径、命令、Token 或 transcript。

## 11. TDD 与 CI

必须先 RED 后 GREEN，覆盖：

1. migration 7 additive/idempotent；
2. artifact 原子写入和 digest 重验；
3. 2.3.13.2 legacy Session 不可接受；
4. accept/reject 幂等且不可反转；
5. Windows/API 不可提交 patch/path/body；
6. exact base + base file hash 才能重放；
7. add/modify/delete 正确；
8. binary/link/path escape/secret/超限全部拒绝；
9. candidate 成功和失败都清理 worktree；
10. `adoption_ready` 不产生 Git commit、push、PR、merge、tag 或 release；
11. Windows真实 WPF review/diff/adoption 布局与刷新保持；
12. 历史 Task Center、Handoff、Return、Broker、Provider 13.2 回归全部保持。

精确头部运行：Windows WPF、Windows Prebuilt Release、Mac Core arm64、Mac Worker arm64。由于 14.1 修改 Worker，Worker 本版必须重新构建；以后未影响 Worker 时继续使用 impact gate 跳过包。

CI 使用 fake Codex/fixture artifact，不消耗真实 Codex 额度。

## 12. 版本与交付

统一升级所有活动版本面到 `2.3.14.1`，在首次版本提交前做仓库级 `2.3.13.2` stale literal 审计。

交付：

- Windows win-x64 预编译安装包；
- Mac Core arm64 离线包；
- Mac Worker arm64 离线包（本版受影响）；
- SHA-256；
- 不额外生成用户侧验证器；
- 最终同时提供清晰的人工验收步骤。

## 13. 非目标

- 自动 commit/push/PR/merge/tag/release；
- Windows 本地 Provider 执行；
- 多 Provider；
- 自动 Usage/额度读取；
- 自动二次 Codex 调用；
- 任意 patch 编辑/上传；
- binary change adoption；
- 把 `adoption_ready` 宣称为 merge-ready。