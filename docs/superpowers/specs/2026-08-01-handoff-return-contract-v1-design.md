# Picotoo Pet Handoff / Return Contract v1 冻结设计规格

- 文档状态：**Approved / Frozen**
- 冻结日期：2026-08-01
- 合同版本：`1.0.0`
- 实施阶段：Phase 10A / 10B
- Phase 2.3 交付：合同、Schema fixture、权限说明与 Control Center 空状态
- 非目标：在 Phase 2.3 安装、调用或适配 Grok Build、Codex、Claude Code

## 1. 目的

Handoff / Return Contract v1 将外部 AI、云端开发服务和人工 Work 约束在 Picotoo Pet 自己的权限、审批、沙盒、审计、本地复验和人工合并闭环中。

External Provider 是可替换执行器，不是事实源、任务队列、权限门、主 UI 或发布系统。Provider 返回内容默认不可信，必须重新校验。

## 2. 冻结信任边界

完整链路：

```text
Mac Handoff Manager
→ Approval Center
→ Windows Dev Broker
→ Provider Adapter
→ Isolated Worktree / Sandbox
→ Return Package
→ Local Validation
→ Human Review
→ PR / Merge / Release Approval
```

任何一步缺失，均不得自动进入下一高风险阶段。

禁止：

- Provider 直接读取 Protected 原件；
- 直接编辑 `main` 或 protected branch；
- 自动 `git push`、merge、tag、release；
- 未批准上传文件；
- 在日志、命令行、Package 中暴露密钥；
- Provider 测试结果直接作为发布证据；
- 两个 Provider 同时编辑同一 worktree；
- 自动切换 Provider 并复用旧批准。

## 3. Handoff 状态机

状态：

`draft | prepared | waiting_approval | approved | staging | running | waiting_tool_approval | stopped_by_policy | returned | validating | ready_for_review | rejected | merged | expired | failed`

规则：

- `draft` 可自动修改；
- `prepared` 后生成 package digest；
- `approved` 绑定 Provider、文件、目标、预算、权限和过期时间；
- 内容变化后回到 `waiting_approval`；
- `waiting_tool_approval` 只允许单次、精确范围批准；
- `stopped_by_policy` 不得自动放宽规则；
- `returned` 仅表示 Provider 停止并返回文件；
- `ready_for_review` 必须由本地验证产生；
- merge/release 需要独立人工批准；
- 过期批准不得恢复会话。

## 4. Handoff Package 目录

```text
handoff-<handoff_id>/
  handoff.json
  MASTER_PROMPT.md
  TASK_SPEC.md
  ACCEPTANCE.json
  ALLOWED_PATHS.json
  DENIED_ACTIONS.json
  EVIDENCE.md
  evidence/
  REPO_CONTEXT.json
  TEST_COMMANDS.json
  OUTPUT_CONTRACT.json
  COST_BUDGET.json
  REDACTION_REPORT.json
  signatures/manifest.sha256
```

### 4.1 handoff.json

必需字段：

- `schema_version`
- `handoff_id`
- `task_id`
- `project_id`
- `trace_id`
- `provider`
- `adapter_version`
- `request_digest`
- `package_digest`
- `sensitivity`
- `repo_url`
- `base_ref`
- `base_commit`
- `allowed_read`
- `allowed_write`
- `required_tests`
- `max_turns`
- `timeout_seconds`
- `budget`
- `created_at`
- `expires_at`
- `approval_id`

约束：

- `request_digest` 绑定目标、Provider、文件清单、权限、预算、测试和过期时间；
- `package_digest` 绑定最终 Package 文件清单；
- `sensitivity` 允许 `public | internal | confidential | protected_derived`；
- Protected 原件不允许进入 Package；
- `base_commit` 必须是不可变 commit SHA；
- allowed path 必须规范化且位于隔离根；
- Provider 变化需要新 digest 和新审批。

### 4.2 MASTER_PROMPT.md

只包含：

- 任务目标；
- 已知背景；
- 输出格式；
- 重要约束；
- 证据引用方式。

不得包含秘密、个人会话、生产凭据或 Protected 原文。

### 4.3 TASK_SPEC.md

明确：

- 具体任务；
- 非目标；
- 允许修改范围；
- 禁止范围；
- 预期行为；
- 错误与回滚要求；
- 完成定义。

### 4.4 ACCEPTANCE.json

每个验收项包含：

- `id`
- `description`
- `type`
- `command | assertion`
- `expected`
- `required`
- `evidence_path`

验收项必须可机器判定或明确标为人工评审，不能使用“看起来正常”。

### 4.5 ALLOWED_PATHS.json

定义：

- 只读目录；
- 可写目录；
- glob；
- 最大文件大小；
- 允许文件类型；
- 是否可创建新文件；
- 是否允许删除。

默认拒绝。生产安装目录、业务原件、模型目录、SSH、浏览器资料、用户文档和系统目录不在允许范围。

### 4.6 DENIED_ACTIONS.json

永久禁止至少包括：

- 修改 main/protected branch；
- push、force push、tag、release；
- 服务、注册表、防火墙、驱动、计划任务修改；
- 凭据管理；
- 下载并执行未知脚本；
- 任意文件上传；
- 删除允许根之外文件；
- 关闭安全检查；
- 危险权限跳过或 yolo/always-approve 模式。

### 4.7 EVIDENCE.md / evidence

- 只收录批准的派生证据；
- 每个文件记录来源、转换、敏感级别和哈希；
- 不复制无关业务数据；
- 引用必须能回溯到本地事实源；
- REDACTION_REPORT 记录删除或替换内容。

### 4.8 REPO_CONTEXT.json

必需字段：

- repo URL；
- base branch/ref；
- base commit；
- worktree 分支命名；
- 构建平台；
- SDK/工具版本要求；
- 仓库规则文件位置；
- 不允许变更的文件；
- 预期 commit 策略。

### 4.9 TEST_COMMANDS.json

每个命令定义：

- command；
- working directory；
- timeout；
- expected exit code；
- 是否允许网络；
- 输出上限；
- 日志路径；
- 必需/可选。

不得允许任意 Shell 命令自由扩展。

### 4.10 OUTPUT_CONTRACT.json

允许返回：

- `diff.patch`
- `changed_files.json`
- 测试、构建、安全报告；
- 明确允许的 artifacts；
- summary 和 questions。

禁止返回 Package 外任意文件或未声明可执行二进制。

### 4.11 COST_BUDGET.json

字段：

- max turns；
- 墙钟时间；
- token/usage 上限；
- 费用上限；
- 并发上限；
- 最大输出大小；
- 网络和工具调用限制。

达到上限必须停止并返回明确原因，不得自动续费或扩展。

## 5. Windows Dev Sandbox

冻结语义根目录：

```text
D:\PicotooPet\DevSandbox\
  worktrees\
  handoff-inbox\
  sessions\
  return-packages\
  quarantine\
```

盘符可在实施时调整，但必须保持独立根、可整体隔离、可清理、不与生产安装、业务原件或 main 工作副本重叠。

每次会话使用独立目录和分支。密钥只在子进程启动时临时注入环境，结束后清除。

## 6. Provider Adapter 统一事件

Adapter 将厂商事件映射为：

- `provider.session.started`
- `provider.plan.updated`
- `provider.progress`
- `provider.tool.requested`
- `provider.tool.approved`
- `provider.tool.rejected`
- `provider.tool.result`
- `provider.usage.updated`
- `provider.warning`
- `provider.policy_stopped`
- `provider.returned`
- `provider.failed`

每个事件包含：

- event_id；
- sequence；
- occurred_at；
- handoff_id；
- session_id；
- provider；
- trace_id；
- payload_version；
- 脱敏 payload。

事件必须按序、可补发、可去重。UI 不以原始终端输出作为主要体验。

## 7. 工具批准

Provider 请求超出 allowlist 的工具时：

1. Adapter 暂停会话；
2. 生成精确工具、参数摘要、路径、网络目标、风险和预计影响；
3. Approval Center 绑定当前 request digest；
4. 用户批准或拒绝一次；
5. 范围变化重新批准；
6. 永久 deny 不允许通过单次批准绕过。

## 8. Return Package

```text
return-<handoff_id>/
  return_manifest.json
  session_events.ndjson
  summary.md
  diff.patch
  changed_files.json
  test_report.json
  build_report.json
  security_report.json
  artifacts/
  questions.md
  signatures/manifest.sha256
```

### 8.1 return_manifest.json

必需字段：

- schema_version；
- handoff_id；
- request_digest；
- package_digest；
- provider；
- adapter/provider version；
- external_session_id；
- base_commit；
- head_commit（存在时）；
- stop_reason；
- started_at / ended_at；
- usage；
- changed file count；
- report refs；
- manifest digest。

### 8.2 changed_files.json

每个文件包含：

- path；
- operation；
- before/after hash；
- additions/deletions；
- permission result；
- generated flag；
- binary flag。

越界文件导致整个 Return 进入 quarantine。

### 8.3 test_report.json

每项包含：

- command；
- environment；
- start/end；
- exit code；
- pass/fail/not_run；
- stdout/stderr refs；
- truncation status。

Provider 声称通过不等于本地通过。

### 8.4 security_report.json

至少检查：

- secret；
- 路径越界；
- 依赖变化；
- 权限变化；
- 危险命令；
- 二进制；
- 网络目标；
- 日志脱敏；
- 许可证/供应链风险。

## 9. 本地验证

Return 进入本地后：

1. 验证 manifest 和所有 SHA-256；
2. 比对 handoff/request digest；
3. 检查 Provider、session、base commit；
4. 检查路径和 changed files；
5. 在干净 worktree 应用 diff；
6. 运行固定测试、构建和安全扫描；
7. 比较副作用；
8. 生成独立 local validation report；
9. 通过后进入 `ready_for_review`；
10. 人工批准 PR/merge；发布另行批准。

任何校验失败不得自动修补原 Return，应保留证据并创建新 revision/handoff。

## 10. Provider 路由规则

- Windows/.NET/WPF：未来优先 Windows 原生 Codex 或 Grok Build；
- Mac Python/launchd：未来优先 Mac 本地/云端工程 Provider；
- 研究和决策文档：ChatGPT Work/人工协作；
- Protected：本地模型和本地工具，禁止上传；
- Provider 结果冲突：第二 Provider 只读审查，人工裁决。

具体 CLI、账号、参数和费用在 Phase 10B 实施当天按官方资料重新核对，不写死 2026-07 参数。

## 11. Control Center 集成

Phase 2.3 “云端开发”页只显示：

- 该功能尚未配置；
- Handoff/Return Contract 版本；
- 未来权限和数据边界；
- 不上传 Protected 原件；
- 未安装 Provider；
- 用户无需操作。

Phase 10A 才实现 Handoff 准备、预览和审批；Phase 10B 实现 Dev Broker、Provider 会话、流式事件和 Return 校验。

## 12. 安全与保留

- Keychain/Credential Manager 保存长期秘密；
- 子进程环境临时注入；
- 命令行、Package、日志不记录密钥；
- Handoff/Return/Session 按敏感级别和期限保留；
- 清理只删除沙盒副本，不删除事实源和审计索引；
- 过期 Package 不可启动；
- Provider 更新不与业务会话同时进行；
- 更新先 sandbox smoke，再允许生产 Handoff。

## 13. 测试门

必须自动证明：

1. Protected 测试文件不能进入 Package；
2. 路径逃逸被拒绝；
3. Provider 无法访问未批准目录；
4. push/main/service/registry 等 deny 生效；
5. request digest 变化使旧批准失效；
6. Provider 切换需要新批准；
7. max turns、超时、预算触发停止；
8. 工具审批只能作用于精确请求；
9. streaming event 顺序、去重和恢复正确；
10. Return 完整哈希可验证；
11. 越界 changed file 进入 quarantine；
12. Provider tests passed 不会绕过本地 CI；
13. Token 和 Protected 内容在日志中被脱敏；
14. 两个 Provider 不共享同一 worktree；
15. merge/release 无独立批准时被拒绝。

## 14. 发布证据

合同发布物：

- Handoff/Return JSON Schema；
- 正例、反例和攻击 fixture；
- digest 规范；
- path/permission policy；
- Adapter 统一事件 Schema；
- 本地验证报告 Schema；
- 兼容矩阵；
- 测试、安全和哈希证据。

## 15. 冻结非目标

本合同不固定：

- 某一 Provider 为永久默认；
- 当前 CLI 参数；
- 账号、套餐和费用；
- 自动 merge 或自动发布；
- Protected 数据上传；
- 生产 Dev Sandbox 盘符；
- Phase 2.3 中的真实 Provider 会话。

## 16. 冻结状态

本合同是 Phase 10A/10B 的唯一外部开发执行边界。Phase 2.3 只交付合同、fixture 和解释性 UI，不安装或调用 Provider。
