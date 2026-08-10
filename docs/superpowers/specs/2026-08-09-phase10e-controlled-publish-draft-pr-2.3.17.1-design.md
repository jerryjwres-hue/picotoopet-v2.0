# Phase 10E 受控 Push + Draft PR 设计

- 产品版本：`2.3.17.1`
- 基线产品版本：`2.3.16.3`
- 基线源码提交：`835656822bd2e1ce199d4a6f4b0d5d568211dfa0`
- 基线 Draft PR：`#19`
- 里程碑：Phase 10E
- 状态：用户已选择方案 A；按明确指令直接进入实现，不再为常规细节暂停确认

## 1. 目标

`2.3.16.3` 已稳定完成：

`Handoff -> Codex Session -> Return -> 人工 Review -> Adoption Candidate -> 本地 Commit Candidate -> commit_ready`

`2.3.17.1` 只补齐下一段外部发布闭环：

`commit_ready -> 新的 digest-bound 人工批准 -> 固定远端候选分支 push -> 独立校验远端 SHA -> 创建 Draft PR -> 独立校验 PR -> pr_ready`

本版不做 CI 自动修复，不 merge，不 tag，不创建 GitHub Release，不修改 `main`。`2.3.18.1` 再进入 PR CI 状态聚合和有界自动修复循环。

## 2. 方案选择

已比较三种方案：

- A：PR base 绑定该 Commit Candidate 对应 Handoff 的已验证开发基线 `base_ref + base_commit`；禁止自由指定，也不自动指向 `main`。
- B：Draft PR 固定指向 `main`。
- C：另设项目级 publication base 配置。

采用 **A**。原因：当前 Handoff 已持久化 `repo_url`、`base_ref`、`base_commit`，因此无需引入新的可漂移输入；同时避免 2.3.17.1 提前跨入 `main`/Merge 安全边界。

## 3. 一次批准覆盖两个外部写动作

为了减少操作摩擦，本版采用一个新的组合审批：

`provider.publish.pr-create-v1`

批准对象不是“允许联网”这种泛化权限，而是一次性绑定以下全部事实：

- `publication_candidate_id`
- `commit_candidate_id`
- `session_id`
- `handoff_id`
- `commit_sha`
- `base_commit`
- `change_set_digest`
- `repo_url`
- `repository_slug`
- `base_ref`
- 固定 `remote_ref`
- 固定 Draft PR title digest
- 固定 Draft PR body digest
- `draft = true`

审批过期时间固定 30 分钟。批准后只允许执行这一组精确外部写动作；审批被拒绝或过期则候选进入终态，不执行网络写入。

## 4. 固定远端分支

远端 ref 不允许 Windows、API 请求或 Worker 自由输入，固定为：

`refs/heads/picotoopet/commit-candidates/<publication_candidate_id>`

短分支名为：

`picotoopet/commit-candidates/<publication_candidate_id>`

禁止 force push。执行前先读取远端 ref：

- ref 不存在：允许 push exact `commit_sha`；
- ref 已存在且 SHA 等于批准的 `commit_sha`：视为幂等恢复，继续；
- ref 已存在但 SHA 不同：`PUBLICATION_REMOTE_REF_CONFLICT`，绝不覆盖。

## 5. Base 不漂移

执行任何 push 前必须查询 `refs/heads/<base_ref>` 的远端 SHA，并要求它仍严格等于 Handoff 中的 `base_commit`。

如果远端基线已经移动：

`PUBLICATION_BASE_MOVED`

本次批准失效，不 push、不自动 rebase、不重新生成提交、不改 PR base。需要重新从新基线进入 Handoff/Codex/Review/Commit 流程。

这是方案 A 的核心安全约束。

## 6. 仓库身份

仓库身份只允许从原始 Handoff 的 `repo_url` 追溯，不接受 Publication API 自由传入。

本阶段仅接受标准 GitHub HTTPS 仓库 URL：

`https://github.com/<owner>/<repo>`

并规范化为 `owner/repo`。拒绝：

- 非 GitHub host；
- URL 中 userinfo/token；
- query/fragment；
- `..`、控制字符或异常 path；
- `file://`、`ext::` 或其他 remote helper 形式。

本项目当前 Handoff 固定仓库为 `jerryjwres-hue/picotoopet-v2.0`。

## 7. Git Push 安全执行

Mac Worker 执行固定 Git 参数，不走 shell：

- `shell=False`
- `GIT_TERMINAL_PROMPT=0`
- `git push --no-verify <validated-repo-url> <commit_sha>:<fixed-remote-ref>`
- 不允许 `--force` / `--force-with-lease`
- push 前后都用固定 `ls-remote --refs` 校验 SHA
- 禁止运行 pre-push hook
- 禁止用户提供 refspec、remote 名称、URL 或 Git 参数

执行前还要读取并拒绝危险本地 Git 配置：

- `remote.*.pushurl`
- `url.*.insteadOf`
- `url.*.pushInsteadOf`
- `remote.*.vcs`
- `core.hooksPath` 不作为信任依据；实际 push 仍强制 `--no-verify`

CI 使用本地 bare remote，并安装恶意 `pre-push` hook，证明 hook 不执行；另测试 remote ref conflict、base moved、crash-after-push 的幂等恢复。

## 8. GitHub Draft PR 执行器

PR 创建使用固定、显式配置的 GitHub CLI executable：

`PICOTOO_GITHUB_CLI_EXECUTABLE`

新增 `GitHubReadinessProbe`，仅执行固定的非交互认证探测；不读取、不记录 token。

Publication readiness 与 Codex readiness 分离。Publication 只要求：

- `provider_repository` 已配置；
- `github_cli_executable` 是可执行文件；
- GitHub CLI 已认证。

PR 命令固定为等价于：

`gh pr create --repo <repository_slug> --base <base_ref> --head <fixed-branch> --draft --title <deterministic-title> --body <deterministic-body>`

所有参数来自数据库中已批准事实；不允许 Windows 输入 title/body/base/head/repo。

CI 不访问真实 GitHub，使用 deterministic fake `gh`。真实远端 Push/PR 只在未来用户对某个具体 Publication Candidate 明确批准后才会发生。

## 9. PR 幂等与独立验证

Worker 在创建 PR 前先用固定 `gh pr list` 查询 exact repo/head/base：

- 没有 PR：创建一个 Draft PR；
- 已存在一个 Draft PR，且 head/base/head SHA 完全匹配：恢复并采用；
- 已存在非 Draft、错误 base、错误 head SHA 或多个冲突候选：`PUBLICATION_PR_CONFLICT`。

创建后必须再执行固定读取，验证：

- repository 精确匹配；
- `isDraft == true`；
- `baseRefName == base_ref`；
- `headRefName == fixed branch`；
- `headRefOid == commit_sha`；
- PR 状态 open。

全部通过才进入 `pr_ready`。

## 10. 状态机

新增 `ProviderPublicationStatus`：

- `waiting_approval`
- `queued`
- `preflight`
- `pushing`
- `verifying_remote`
- `remote_ready`
- `creating_pr`
- `verifying_pr`
- `pr_ready`
- `rejected`
- `cancelled`
- `base_moved`
- `remote_ref_conflict`
- `auth_unavailable`
- `policy_blocked`
- `push_failed`
- `pr_conflict`
- `pr_failed`
- `failed`

`pr_ready` 只表示“精确 Commit 已发布到固定候选分支，并存在经过复核的 Draft PR”。它不是 CI-ready、merge-ready 或 release-ready。

## 11. 数据库

新增 Migration 10 和表 `provider_publication_candidates`，关键字段：

- `publication_candidate_id` PK
- `commit_candidate_id` UNIQUE FK
- `session_id`
- `handoff_id`
- `status`
- `repo_url`
- `repository_slug`
- `base_ref`
- `base_commit`
- `commit_sha`
- `change_set_digest`
- `remote_ref` UNIQUE
- `remote_branch`
- `approval_id` UNIQUE FK
- `idempotency_key` UNIQUE
- `pr_title_digest`
- `pr_body_digest`
- `pr_number`
- `pr_url`
- `pr_head_sha`
- `validation_json`
- `failure_code`
- timestamps
- `preview_json`

SQLite 继续是 Mac Core 唯一权威事实源。

## 12. Mac Core 服务/API

新增：

- `providers/publication_models.py`
- `providers/publication_service.py`
- `providers/publication_execution.py`
- `providers/github_readiness.py`
- `api/routes/provider_publications.py`

API：

- `POST /api/v1/provider-commit-candidates/{id}/publication/prepare`
  - empty body
  - 只有 `commit_ready` 可准备
  - 创建组合审批
- `GET /api/v1/provider-publication-candidates?limit=100`
- `GET /api/v1/provider-publication-candidates/{id}`

不提供修改 repo/base/head/title/body/ref 的 API。

## 13. Mac Worker

新增固定任务类型：

`provider.publish.pr-create-v1`

只有审批状态为 Approved 才入队。`max_attempts=1`，因为幂等恢复由 Publication 状态机和远端事实验证完成，不能靠 Queue 自动重复外部写。

Worker 任务 payload 继续遵守 2.3.16.3 修复后的原则：只包含该任务自己的严格业务字段，不由 Workflow Engine 注入元数据。

## 14. Windows 原生 WPF

在现有“云端开发 -> Review/Adoption/Commit”区域继续向下增加“远端发布候选”块，不另造浏览器页面。

显示：

- Publication status
- 固定 repository
- 固定 base ref + base SHA
- 固定 remote branch
- commit SHA
- Draft PR number/url（成功后）
- validation checks / failure code 的安全摘要

按钮：

- `准备 Push + Draft PR`
- `刷新发布状态`

只有 `commit_ready` 且该 Commit Candidate 尚无 Publication Candidate 时可准备。按钮只请求审批，不直接 push。

明确文案：

`pr_ready != CI-green != merge-ready；2.3.17.1 不会自动 merge、tag 或 release。`

Approval Center 继续承担批准/拒绝，不在 Review Panel 中复制审批 UI。

## 15. 审批摘要扩展

`HandoffApprovalService._SUMMARY_KEYS` 增加安全字段：

- `publication_candidate_id`
- `repository_slug`
- `base_ref`
- `remote_ref`
- `commit_sha`
- `pr_title_digest`
- `pr_body_digest`
- `draft`

不把 token、credential、完整 PR body、用户文件正文或任意 Git 配置暴露给 Windows。

## 16. 错误与恢复

关键 crash 窗口：

1. push 成功、DB 尚未更新：重启后 `ls-remote` 发现 fixed ref 已精确等于批准 SHA，恢复到 `remote_ready`；
2. PR 创建成功、DB 尚未记录：重启后 exact PR 查询发现匹配 Draft PR，采用现有 PR，不重复创建；
3. base 在批准后移动但尚未 push：停止为 `base_moved`；
4. remote ref 被其他主体写成不同 SHA：停止为 `remote_ref_conflict`；
5. GitHub CLI 未认证：`auth_unavailable`，不反复联网重试；
6. 任意政策校验失败：`policy_blocked`。

所有失败保留结构化 `failure_code`，不保存命令 stdout/stderr 中可能出现的凭据信息。

## 17. TDD/CI 测试矩阵

先 RED 后 GREEN。至少覆盖：

- 非 `commit_ready` 拒绝 prepare；
- commit SHA 缺失拒绝；
- Handoff repo/base provenance 精确追溯；
- publication approval scope 全字段精确匹配；
- prepare empty body；
- 幂等 prepare 与冲突；
- Migration 10；
- 固定 remote ref；
- base moved 在 push 前阻断；
- malicious pre-push hook 不执行；
- dangerous URL rewrite/pushurl 被拒绝；
- remote ref exact reuse；
- remote ref conflict 不覆盖；
- crash-after-push 恢复；
- fake GitHub duplicate Draft PR 恢复；
- non-Draft / wrong base / wrong head SHA 冲突；
- 最终 PR 必须 Draft；
- 无 merge/tag/release 命令；
- Windows 不存在 repo/base/head/title/body/ref 输入控件；
- Windows WPF Measure/Arrange/UpdateLayout smoke；
- 2.3.16.3 Projects/Automation/Health/Diagnostics 非回归；
- product version `2.3.17.1` 全链一致；
- Mac Core / Mac Worker / Windows 原生 CI 和正式预编译包。

## 18. 发布/验收边界

本版 CI 只使用本地 bare Git remote + fake GitHub CLI，因此不会写真实 GitHub。

正式安装包必须同时生成：

- Windows win-x64 预编译包
- Mac Core arm64
- Mac Worker arm64

原因：三端均有合同/运行时变化，不能跳过 Worker。

交付必须包含 SHA-256、独立核验报告和人工验收标准。

真实 Push + Draft PR 属于外部写动作；只有未来用户对某个具体 Publication Candidate 在 Approval Center 明确批准后才允许执行。`main`、merge、tag、release 在本版本始终禁止。
