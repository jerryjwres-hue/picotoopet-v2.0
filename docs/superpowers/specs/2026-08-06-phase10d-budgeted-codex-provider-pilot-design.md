# Phase 10D-A 受控低预算 Codex Provider 试点设计规格

- 文档状态：**Approved direction / Written-spec review pending**
- 产品版本：`2.3.13.2`
- 基线版本：`2.3.13.1`
- 基线提交：`65d5ba0ef5a4ac6f6b3ca61b0f852599d1286d6f`
- 合同版本：Handoff / Return Contract `1.0.0`
- Provider：OpenAI Codex（单 Provider 试点）
- 实施里程碑：Phase 10D-A

> Phase 10C 已用于 `2.3.13.1` 的事件流冷启动恢复收口。真实 Provider 试点采用 Phase 10D-A，避免里程碑与制品含义重名。

## 1. 目标

在保留 Mac Core + SQLite 为唯一事实源、Windows 原生 WPF 为用户控制面、Mac Worker 为执行面的前提下，为已批准 Handoff 增加一个真实但严格受控的 OpenAI Codex 执行闭环：

1. Windows 用户选择一个精确、未过期且绑定 Codex 的 approved Handoff；
2. 用户先在 PC 的 Codex Usage 页面或 Codex 应用中人工查看可用额度；
3. 用户在 Windows 原生 WPF 中明确确认“已检查额度并允许一次低预算调用”；
4. Mac Core 校验审批、摘要、预算、并发、一次性额度确认和 Provider 状态；
5. Mac Worker 在本机隔离 Git worktree 中启动一个受限 Codex CLI Session；
6. Codex 只能读取/修改 Handoff 允许的路径，不能获得任意命令、路径、环境变量或凭据输入；
7. 达到时间、turn、输出、文件数、策略或取消边界时立即停止；
8. Provider 输出被规范化为现有 Return Contract，并由 Mac Core 独立验证；
9. Windows 只显示安全事实、预算使用、变更清单、测试摘要和隔离结果；
10. 不自动提交、push、创建 PR、merge、tag、release，也不自动续费或放宽预算。

本版本的产品价值不是让 Codex 常驻工作，而是把它作为普通 Worker 无法完成时的低频升级能力，并对每次调用建立人工确认、预算、沙箱、审计、Return 校验和本地复验闭环。

## 2. 已评估方案

### 2.1 采用方案：Windows 控制面 + Mac 执行面

- Windows：Handoff、审批、额度人工确认、启动、取消、状态和安全结果；
- Mac Core：事实源、状态机、预算账本、策略和 Return 校验；
- Mac Worker：Codex CLI、隔离 worktree、进程树和本地测试；
- Codex 凭据只存放在实际执行的 Mac 用户安全存储中。

优点：仓库、worktree、测试工具链、Provider 子进程、Return 和清理逻辑位于同一执行边界；不需要跨机器复制 Codex 凭据或同步可写工作区。

该控制面/执行面决定已由用户明确批准，覆盖早期合同文档中 Windows Dev Broker 直接承载 Provider Adapter 的预留方案。Windows 仍是唯一日常用户控制面，不成为 Worker。

### 2.2 未采用：Windows 直接执行 Codex

优点是用户可以在同一 PC 登录和执行。缺点是目标仓库、Mac 测试工具链和 Return 事实源跨机器分裂，需要新增双端仓库同步、凭据、进程恢复和冲突处理，扩大首版故障面。

### 2.3 未采用：多 Provider 插件系统

首版同时支持 Codex、Claude Code、Grok Build 会引入多套认证、预算、输出和错误语义。2.3.13.2 只实现一个固定 Codex Adapter；Provider 变化必须产生新 digest、新审批和后续独立设计。

## 3. 不可突破的边界

- PR 保持 Draft，不合并 `main`。
- 用户 Windows/Mac 日常设备只安装预编译包，不编译项目源码。
- Mac Core + SQLite 是 Handoff、Provider Session、预算和 Return 的唯一事实源。
- Windows 不持久化 Codex OAuth/API 凭据，不接收 Mac Keychain 内容。
- Mac Core 数据库、日志、事件、Return、错误正文和 WPF 均不得包含 Codex refresh token、API key、Authorization 或完整 Provider stdout/stderr。
- 不抓取、解析或自动登录 Codex Usage 网页。
- 额度无法机器可靠读取时显示 `unknown`，不得伪造余额。
- 不自动购买 credits，不启用或修改 auto top-up，不升级套餐。
- 每个 approved Handoff 最多启动一次真实 Provider Session；再次使用必须重新准备并重新审批。
- 不自动切换 Provider，不复用旧批准。
- 不允许任意命令、任意路径、任意模型、任意网络工具、任意环境变量或任意测试命令输入。
- 不允许 Provider 修改 `main`、protected branch、原始工作区或允许根之外文件。
- 不自动 commit、push、PR、merge、tag 或 release。
- Protected 原件、Raw Evidence、浏览器资料、SSH、用户文档、系统目录和生产安装目录永久不进入 Provider 工作区。

## 4. 额度确认和低频策略

### 4.1 两层预算

**账户层状态**只允许：

- `confirmed_available`：用户在外部 Codex Usage 中人工确认可用；
- `confirmed_low`：用户确认额度接近限制，不允许启动；
- `confirmed_exhausted`：用户确认已达限制，不允许启动；
- `unknown`：未确认或无法可靠读取，不允许自动启动。

PicotooPet 不把人工确认描述为 OpenAI 的机器证明，也不声称能够计算整个账户精确余额。

**本地 Provider 预算**由 Mac Core 强制执行，不能由 Windows任意放大：

- 同时运行真实 Codex Session：`1`；
- 每个 Handoff：最多 `1` 个真实 Session；
- 最大 turn：`8`；
- 最大墙钟时间：`900` 秒；
- 自动重试：`0`；
- 仅允许连接恢复一次，且不得重新提交任务；
- 最大 changed files：`5`；
- 单文件最大：`64 KiB`；
- Return 总大小最大：`256 KiB`；
- 最大安全事件：`100`；
- 网络工具：禁止；
- 自动充值：禁止；
- 自动扩大预算：禁止。

达到任何上限必须停止并记录固定原因，不能通过创建多个 Session 绕过。

### 4.2 人工额度确认

Windows 页面提供固定确认动作：

`我已在 Codex Usage 中检查额度，并允许此 Handoff 启动一次低预算 Codex Session。`

确认记录绑定：

- `handoff_id`
- `request_digest`
- `package_digest`
- `provider=codex`
- 固定预算摘要
- 确认状态
- 确认时间
- 短期过期时间（15 分钟）
- 当前用户审批 ID

确认内容、Handoff 或预算变化后必须重新确认。Windows 不提供余额数字自由输入。

## 5. 认证设计

### 5.1 PC

PC 可以登录 Codex Web/App 查看 Usage，但该登录不授权 PicotooPet Windows 进程读取浏览器会话、Cookie、Token 或余额接口。Windows 只保存 Mac Core 返回的人工确认事实。

### 5.2 Mac

Codex CLI 在实际执行的 macOS 用户下完成一次 ChatGPT 登录。凭据由 Codex/操作系统本地安全存储管理：

- PicotooPet 不复制、导出或显示凭据；
- Worker 只检测固定 Codex CLI 是否可执行和认证状态是否可用；
- 认证状态只投影为 `ready | not_authenticated | unavailable | policy_blocked`；
- 不把凭据注入命令参数；
- 不允许 Windows 发起登录或传入 API key。

2.3.13.2 安装包不得自动安装 Codex CLI、自动登录或修改用户 OpenAI 账户设置。安装与登录是一次性受控前置条件，并在实机验收时完成。

## 6. Provider Session 状态机

允许状态：

```text
requested
-> waiting_usage_confirmation
-> waiting_provider_ready
-> staging
-> running
-> returning
-> validating
-> ready_for_review
```

终态：

```text
cancelled | timed_out | stopped_by_budget | stopped_by_policy |
provider_failed | return_quarantined | validation_failed | failed
```

规则：

- 只有精确 digest 绑定、未过期的 approved Handoff 可创建 Session；
- 同一 Idempotency-Key 返回同一 Session；
- 同一 Handoff 已存在真实 Provider Session 时拒绝新建；
- `running` 只能由 Worker lease 和 Provider 子进程事实推进；
- Windows 不得自行宣布完成、通过或隔离；
- `ready_for_review` 只能由 Mac Core 本地验证产生；
- `cancelled`、`timed_out`、`stopped_by_budget` 和 `stopped_by_policy` 均不得自动重试；
- 任何内容变化必须回到新 Handoff、新 digest 和新审批。

## 7. Mac Core 设计

### 7.1 持久化

新增 migration，建立 `provider_sessions` 和 `provider_usage_confirmations` 安全事实表。

`provider_sessions` 至少包含：

- `session_id`
- `handoff_id`
- `provider`
- `status`
- `request_digest`
- `package_digest`
- `budget_json`（固定白名单标量）
- `turns_used`
- `elapsed_seconds`
- `changed_file_count`
- `return_id`
- `failure_code`
- `idempotency_key`
- `created_at`
- `updated_at`
- `finished_at`

不得保存 prompt 全文、Provider 原始 transcript、凭据、任意环境变量、任意路径或完整 stdout/stderr。

`provider_usage_confirmations` 保存绑定字段、状态、确认时间和过期时间，不保存账户余额或浏览器证据。

### 7.2 API

新增固定 API：

- `GET /api/v1/providers/codex/status`
- `POST /api/v1/handoffs/{handoff_id}/provider-usage-confirmation`
- `POST /api/v1/handoffs/{handoff_id}/provider-sessions/codex`
- `GET /api/v1/provider-sessions?limit=100`
- `GET /api/v1/provider-sessions/{session_id}`
- `POST /api/v1/provider-sessions/{session_id}/cancel`
- `POST /api/v1/provider-sessions/{session_id}/return`

所有写操作要求 `Idempotency-Key`。模型 `extra="forbid"`，请求体有界，不接受任意 Provider 参数、命令、路径、模型名、环境变量、密钥或自由 JSON。

### 7.3 预算账本

Mac Core 在 Session 创建前和每次 Worker 进度事件后检查预算。预算事实必须包含：

- 固定上限；
- 当前使用；
- 停止原因；
- 是否允许继续。

Windows 只显示事实，不计算剩余额度或终态。

## 8. Mac Worker 和 Codex Adapter

### 8.1 固定 Adapter

新增注册任务类型，例如：

`provider.codex.handoff-v1`

Adapter 使用结构化参数，不拼接 shell 命令。执行器只允许固定 Codex CLI 路径、固定子命令、固定模型策略和由 Mac Core 生成的只读 Handoff package。

禁止：

- `shell=True`；
- bash/zsh 命令字符串；
- 用户提供 CLI flag；
- arbitrary tool approval；
- yolo/always-approve；
- 网络工具；
- Provider 自行安装依赖；
- Provider 修改 Git 配置或凭据。

### 8.2 隔离 worktree

Worker 从服务器拥有的固定 repo 和 immutable base commit 创建 Session 独占 worktree：

- worktree 根由应用配置推导，不接受客户端路径；
- 分支名由 `session_id` 确定；
- 创建前验证 repo identity、base commit 和 clean source；
- 拒绝 symlink/reparse/路径逃逸；
- 只复制批准 Handoff package；
- Provider 只写 allowed_write；
- 结束后生成 diff 和安全 Return，再删除 worktree；
- 清理失败进入固定失败状态并阻止新 Session。

### 8.3 进程和输出

- Codex 子进程位于独立 macOS process group；
- 取消、超时、预算停止后终止整个进程组；
- stdout/stderr 有界并实时脱敏；
- 原始 transcript 不进入 Windows、Mac Core DB 或正式 Return；
- 只提取固定阶段、turn、token/credit 信息（仅当 Codex 稳定结构化输出明确提供）、文件变化和错误码；
- 无机器可读 usage 时记录 `provider_usage_unknown=true`，不得推算。

## 9. Return 和本地验证

真实 Codex 输出必须转换为 Handoff / Return Contract v1，至少包含：

- `return_manifest.json`
- `session_events.ndjson`
- `summary.md`
- `changed_files.json`
- `diff.patch`
- `test_report.json`
- `build_report.json`
- `security_report.json`
- `questions.md`
- `signatures/manifest.sha256`

Mac Core 独立验证：

- Session、Handoff、request/package digest 和 base commit 绑定；
- 文件集合、大小、哈希、事件顺序；
- changed files 数量和允许路径；
- 无秘密、Protected、Raw Evidence 或未声明二进制；
- diff 不修改 protected branch、CI 凭据、安装签名或允许根之外内容；
- Provider 自报测试不作为正式发布证据；
- 本地固定测试必须重新执行，才能进入 `ready_for_review`。

## 10. Windows 原生 WPF 体验

现有“云端开发”页面增加 **Codex Provider 试点**区域：

- Provider 状态：可用、未认证、不可用、策略阻止；
- approved Handoff 选择；
- Handoff digest、允许路径、固定测试和预算；
- 额度状态：未确认、确认可用、确认偏低、确认耗尽；
- “记录额度确认”；
- “申请一次低预算 Codex Session”；
- “取消 Session”；
- 最近 Session 列表和安全预览；
- 阶段、耗时、turn、文件数、停止原因、Return 和本地验证状态。

页面不得增加：

- Codex Token/API key 输入；
- 任意 prompt、命令、路径、模型或环境变量输入；
- 文件选择器、拖放、终端、WebView 或 localhost UI；
- 自动充值、套餐变更、push、PR、merge、tag 或 release。

真实 STA WPF 测试必须覆盖 DataBind、Measure、Arrange、UpdateLayout、ItemsSource 替换、取消和错误状态，且不得再次引入只读属性 TwoWay 绑定崩溃。

## 11. 错误码

至少包括：

- `PROVIDER_HANDOFF_NOT_APPROVED`
- `PROVIDER_HANDOFF_DIGEST_MISMATCH`
- `PROVIDER_USAGE_CONFIRMATION_REQUIRED`
- `PROVIDER_USAGE_CONFIRMATION_EXPIRED`
- `PROVIDER_USAGE_LOW`
- `PROVIDER_USAGE_EXHAUSTED`
- `PROVIDER_ALREADY_USED_FOR_HANDOFF`
- `PROVIDER_CONCURRENCY_LIMIT`
- `PROVIDER_CODEX_UNAVAILABLE`
- `PROVIDER_CODEX_NOT_AUTHENTICATED`
- `PROVIDER_WORKTREE_CREATE_FAILED`
- `PROVIDER_WORKTREE_ESCAPE`
- `PROVIDER_PROCESS_OUTPUT_TOO_LARGE`
- `PROVIDER_TIMED_OUT`
- `PROVIDER_CANCELLED`
- `PROVIDER_BUDGET_EXCEEDED`
- `PROVIDER_POLICY_BLOCKED`
- `PROVIDER_RETURN_QUARANTINED`
- `PROVIDER_WORKTREE_CLEANUP_FAILED`

错误正文使用固定安全文案，不回显凭据、命令、路径、prompt、stdout/stderr 或 Return 正文。

## 12. TDD 和原生 CI

必须先 RED 后 GREEN，并证明：

1. migration 安全、幂等且不修改历史任务/Handoff/Return；
2. 额度确认绑定精确 digest、预算和 15 分钟 expiry；
3. 未确认、偏低、耗尽、过期均不能启动；
4. approved Handoff、单 Session、单并发和幂等行为正确；
5. Windows 不接收或持久化 Codex 凭据；
6. Mac Core 响应无凭据、原始 transcript、任意路径或命令；
7. Adapter 不使用 shell 字符串，不接受用户 flag；
8. worktree 固定根、base commit 和 allowed paths 被强制；
9. 超时、取消、预算停止清理完整进程组和 worktree；
10. 输出、事件、文件数、单文件和 Return 总大小有界；
11. 额外文件、秘密、路径逃逸、错误 digest/base/Session 被隔离；
12. Provider 自报测试不能直接成为发布证据；
13. 本地测试通过后才可 `ready_for_review`；
14. 真实 STA WPF 页面和历史 Task Center/Approval/Return/事件流回归通过；
15. 版本字面量在首次版本提交前完成仓库级审计；
16. Windows WPF、Windows Release、Mac Core arm64、Mac Worker arm64 四条精确头部原生门通过。

CI 不使用用户 Codex 凭据，不执行付费 Provider 调用。使用确定性的假 Codex 可执行程序/协议夹具验证 Adapter、预算、取消、Return 和清理边界。

## 13. 打包和验收

正式候选必须生成并独立校验：

- Windows `win-x64` 预编译安装包；
- Mac Core `arm64` 离线包；
- Mac Worker `arm64` 离线包；
- SHA-256、Manifest、构建报告、安装/升级/恢复/回滚证据；
- `source_build_on_user_pc=false`；
- `source_build_on_user_mac=false`。

自动 CI 验收后，仍需一次真实环境验收：

1. PC 中人工查看 Codex Usage；
2. Mac 中完成 Codex CLI 一次性登录并确认 Provider 为 `ready`；
3. 在 Windows 创建/使用一个重新审批、绑定 Codex 和固定低预算的 Handoff；
4. 记录一次额度确认；
5. 启动一个 Session；
6. 证明隔离 worktree、最多 5 个允许文件、预算和取消边界；
7. Return 通过 Mac Core 独立校验和本地固定测试；
8. Windows 显示 `ready_for_review`；
9. 原始工作区、main、远端仓库和 OpenAI 账户设置未被修改；
10. 不自动产生 commit、push、PR、merge、tag 或 release。

只有该实机闭环通过，2.3.13.2 才可标记为实机接受。

## 14. 非目标

- 多 Provider 插件系统；
- Windows 本地 Codex 执行节点；
- 自动额度抓取或余额预测；
- 自动充值；
- 后台定时 Codex 任务；
- 多 Session 并发；
- 任意 prompt/模型/工具配置；
- 自动 commit、push、PR、merge、tag、release；
- 公开签名发行版。
