# Phase 10B-B 内置 Mock Provider Dev Broker 沙盒闭环设计规格

- 文档状态：**Approved / Frozen for implementation**
- 产品版本：`2.3.12.1`
- 基线版本：`2.3.11.1`
- 合同版本：Handoff / Return Contract `1.0.0`
- 实施范围：Phase 10B 第二条低风险垂直切片

## 1. 目标

在不安装、不登录、不调用 Codex、Grok Build 或任何外部 Provider 的前提下，建立 Windows Dev Broker 的首个可执行安全闭环：

1. Windows Control Center 为已批准 Handoff 向 Mac Core 申请一个固定 Mock Broker Session；
2. Windows 使用现有 `Picotoo Pet AI.exe` 的无界面子进程模式运行内置 Mock Provider；
3. 子进程只在应用自有的隔离沙盒中创建固定测试夹具和一个允许的文本变更；
4. 父进程使用 Windows Job Object 执行 30 秒硬超时、取消和进程树清理；
5. Windows 将严格有界、会话绑定的 Mock Return JSON 信封提交给 Mac Core；
6. Mac Core 独立验证会话令牌、Handoff digest、沙盒策略、文件集合、内容哈希、事件顺序和秘密扫描；
7. 验证通过后复用现有 Return 安全投影，明确标记仅完成沙盒和合同验证；
8. Windows 原生 WPF 显示 Broker Session、固定命令策略、超时、取消、Return 与验证状态；
9. 刷新、网络错误和 ItemsSource 替换不得清除同一 Session 或 Return 的安全预览。

本版本证明 Dev Broker 的进程隔离、沙盒边界、超时取消、Return 导回和事实持久化可以工作。它不执行真实 Provider、真实仓库、Git worktree、代码编译、项目测试、PR、merge 或 release。

## 2. 架构决定

### 2.1 不新增安装服务或第二个产品程序

正式用户界面仍然只有现有原生 WPF：

```text
Picotoo Pet AI.exe
```

Mock Provider 使用同一预编译 EXE 的内部无界面子进程入口：

```text
Picotoo Pet AI.exe --dev-broker-mock-child --session-id <uuid>
```

该入口：

- 不创建窗口；
- 不接受命令字符串、路径、Provider 参数或凭据；
- 只接受格式严格的 `session_id`；
- 沙盒路径由程序根据 `%LOCALAPPDATA%` 和 `session_id` 内部推导；
- 只输出一个有界 JSON Return 信封到标准输出；
- 标准错误只允许固定错误码，不输出文件正文、Token 或环境变量。

这样保留真实进程边界和超时/取消能力，同时不增加服务、管理员权限、启动项或新的可执行文件白名单。

### 2.2 Mac Core 继续是唯一事实源

Mac Core 新增 `broker_sessions` 持久化域。Windows 只申请会话、执行固定 Broker 子进程并提交严格 Return 信封；最终状态、Return 记录和安全检查都由 Mac Core 写入 SQLite。

Windows 不得自行宣布 `completed`、`contract_validated` 或 `quarantined`。界面只展示 Mac Core 返回的事实。

### 2.3 沙盒模式而非真实 Git worktree

本切片使用应用自有的**隔离沙盒目录**，而不是用户仓库或真实 Git worktree：

```text
%LOCALAPPDATA%\PicotooPetV2\DevBroker\sessions\<session_id>\
```

原因：本版本要先冻结进程、目录、Return 和清理边界，不向用户电脑引入 Git、SDK、源码仓库或 Provider 依赖。真实 Git worktree 和真实 Provider Adapter 属于后续独立版本。

沙盒固定包含：

- `fixture/base/project.json`
- `fixture/base/docs/README.md`
- `workspace/project.json`
- `workspace/docs/README.md`
- `workspace/docs/mock-provider-proof.txt`
- `return/return-envelope.json`

Mock Provider 只允许新建：

```text
workspace/docs/mock-provider-proof.txt
```

内容由 `session_id`、Handoff digest 和固定模板确定，不含用户文件、日志或凭据。

## 3. Broker Session 状态机

允许状态：

```text
reserved -> running -> returning -> completed
                    \-> cancelled
                    \-> timed_out
                    \-> failed
                    \-> quarantined
```

规则：

- 只有 `approved` Handoff 可以 `reserved`；
- 同一 `Idempotency-Key` 和同一 Handoff 返回同一 Session；
- 相同幂等键绑定不同 Handoff 必须冲突；
- Session 固定 Provider 为 `local-mock-dev-broker`；
- 超时固定为 30 秒，不接受客户端覆盖；
- `completed` 只在 Mac Core 成功验证 Return 后写入；
- 取消、超时和失败必须终止完整进程树；
- `quarantined` 不自动重试、不放宽策略，也不把 Handoff 推进到可合并状态。

## 4. Session 令牌与幂等

Mac Core 使用现有 API Token 作为 HMAC 密钥，确定性生成短期 Session capability：

```text
HMAC-SHA256(api_token, "broker-session-v1:" + session_id + ":" + handoff_id)
```

要求：

- capability 不写入 SQLite；
- capability 不进入日志、审计详情、Return 预览或错误正文；
- Session 创建重试可返回同一 capability；
- Return 提交必须同时通过 Bearer 认证和 capability 常量时间比较；
- Session ID、Handoff ID、request/package digest 和 capability 必须全部绑定。

## 5. Mac Core 设计

### 5.1 Migration 5

新增 `broker_sessions` 表，至少包含：

- `session_id`
- `handoff_id`
- `status`
- `provider`
- `timeout_seconds`
- `request_digest`
- `package_digest`
- `return_id`
- `event_count`
- `sandbox_digest`
- `failure_code`
- `idempotency_key`
- `created_at`
- `updated_at`
- `finished_at`

只保存安全事实，不保存 capability、文件正文、任意路径、命令、原始 stdout/stderr 或环境变量。

### 5.2 API

新增：

- `POST /api/v1/handoffs/{handoff_id}/broker-sessions/mock`
- `GET /api/v1/broker-sessions?limit=100`
- `GET /api/v1/broker-sessions/{session_id}`
- `POST /api/v1/broker-sessions/{session_id}/return`
- `POST /api/v1/broker-sessions/{session_id}/cancel`

写操作均要求 `Idempotency-Key`。Return 提交额外要求：

```text
X-Picotoo-Broker-Session: <capability>
```

Return API：

- 只接受 `application/json`；
- 请求体最大 128 KiB；
- 不接受 multipart、base64、任意路径、命令、环境变量、Provider 配置或二进制；
- Pydantic 模型 `extra="forbid"`；
- 文件名采用枚举，不采用自由字符串路径。

### 5.3 Mock Return 信封

固定 Provider：

```text
local-mock-dev-broker
```

固定文件：

- `return_manifest.json`
- `session_events.ndjson`
- `summary.md`
- `changed_files.json`
- `test_report.json`
- `build_report.json`
- `security_report.json`
- `questions.md`
- `changes/docs/mock-provider-proof.txt`
- `signatures/manifest.sha256`

约束：

- changed file 数量必须等于 1；
- 唯一 changed file 必须为 `docs/mock-provider-proof.txt`；
- test/build 必须为 `not_run`；
- 事件固定为 `broker.started`、`broker.sandbox.ready`、`provider.returned`、`broker.return.submitted`，sequence 从 1 连续递增；
- 所有内容必须为 UTF-8 文本；
- 每文件最大 32 KiB，总体最大 128 KiB；
- SHA-256 覆盖必须精确；
- request/package digest、Handoff ID 和 Session ID 必须与事实源一致；
- 秘密模式、Protected 原件、Raw Evidence、Authorization、Token、密码或私钥片段触发整体隔离。

### 5.4 Return 兼容

现有 Phase 10B-A `local-contract-self-test` 零变更流程保持不变。

`ReturnRecord` 只扩展为允许两个固定 Provider：

- `local-contract-self-test`
- `local-mock-dev-broker`

changed file 数量允许 `0..1`，但每个 Provider 使用独立固定策略：

- self-test 必须为 0；
- mock broker 必须为 1 且路径固定。

成功状态仍为 `contract_validated`。界面必须同时展示 Broker Session 为 `completed`，并明确：未执行项目测试、构建或真实 Provider。

## 6. Windows Dev Broker 设计

### 6.1 组件边界

新增独立、可单元测试的组件：

- `BrokerCommandPolicy`：只允许内部枚举动作，不接受命令字符串；
- `BrokerSandboxPaths`：从受信任 LocalAppData 根和 UUID 推导路径；
- `BrokerSandboxBuilder`：创建固定 fixture/workspace，拒绝 reparse point；
- `MockProviderChild`：生成唯一允许的文本变更和 Return 信封；
- `WindowsJobObject`：进程树生命周期；
- `DevBrokerProcessRunner`：固定参数启动、64 KiB 输出上限、30 秒超时和取消；
- `MacCoreBrokerClient`：有界 HTTP、同一幂等键单次重试；
- `ControlCenterSession.Broker`：把 Mac Core 事实投影到现有 WPF ViewModel。

### 6.2 进程安全

父进程必须：

- `UseShellExecute=false`；
- 不调用 `cmd.exe`、PowerShell、bash、WSL 或脚本宿主；
- 不拼接命令字符串；
- 只传固定开关和规范 UUID；
- 关闭继承句柄；
- 绑定 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`；
- stdout/stderr 分别限制 64 KiB；
- 超时或取消后等待进程树退出并验证无残留；
- 无论成功或失败都清理沙盒，最多保留安全摘要，不保留用户可执行内容。

### 6.3 WPF 产品体验

“云端开发”页面在现有 Handoff / Return 区域新增 **Phase 10B-B Mock Dev Broker**：

- 选择 approved Handoff；
- “启动 Mock Provider 沙盒验证”；
- “取消 Broker Session”；
- “刷新 Broker 状态”；
- 最近 Session 列表；
- Session 状态、固定 Provider、30 秒超时、沙盒模式；
- Return ID、digest、1 个固定文本变更和 4 个脱敏事件；
- 明确提示未安装、未登录、未调用真实 Provider，未运行项目测试或构建。

页面不得增加：

- 文件选择器、拖放；
- 路径框、命令框、终端；
- Provider 名称或参数输入；
- 凭据输入；
- 浏览器、WebView、localhost UI；
- 自动 PR、merge、tag 或 release。

## 7. 错误处理

固定错误码至少包括：

- `BROKER_HANDOFF_NOT_APPROVED`
- `BROKER_SESSION_CONFLICT`
- `BROKER_SESSION_NOT_FOUND`
- `BROKER_SESSION_CAPABILITY_INVALID`
- `BROKER_OUTPUT_TOO_LARGE`
- `BROKER_OUTPUT_INVALID`
- `BROKER_SANDBOX_ESCAPE`
- `BROKER_REPARSE_POINT_REJECTED`
- `BROKER_COMMAND_DENIED`
- `BROKER_TIMED_OUT`
- `BROKER_CANCELLED`
- `BROKER_PROCESS_CLEANUP_FAILED`
- `BROKER_RETURN_QUARANTINED`

错误消息只使用固定中文文案，不回显路径、命令、环境变量、stdout/stderr 或 Return 正文。

## 8. TDD 与原生门

必须先 RED 后 GREEN，并证明：

1. migration 5 从 migration 4 安全升级且幂等；
2. 只有 approved Handoff 可以创建 Session；
3. 幂等创建、冲突和 capability 重放行为正确；
4. capability 不持久化、不出现在安全投影；
5. Return body、文件数、文件大小和总大小有界；
6. 额外字段、额外文件、错误 provider、错误 changed file、digest/session/Handoff 不匹配均隔离；
7. Token、Authorization、密码、私钥、Protected 和 Raw Evidence 被拒绝；
8. Windows command policy 拒绝字符串命令和所有未登记动作；
9. 沙盒路径只能位于 LocalAppData 固定根，拒绝 traversal、盘符、UNC 和 reparse point；
10. Mock 子进程成功生成固定 Return；
11. 超时、取消和异常均清理完整进程树；
12. 输出上限和无效 JSON 不会进入 UI 或日志；
13. typed client 使用同一幂等键单次重试；
14. 同一 Session/Return 在 ItemsSource 替换、刷新和有界网络错误后保持预览；
15. 真实 STA WPF 执行 DataBind、Measure、Arrange、UpdateLayout；
16. 2.3.11.1 的 Handoff、审批、Results、Task Center、Return self-test 和导航回归继续通过；
17. Windows 正式 Release、Windows WPF、Mac Core arm64 和 Worker 影响检测全部通过；
18. 用户电脑只安装预编译包，不安装 SDK，不编译源码。

## 9. 发布与验收

- 唯一用户版本更新为 `2.3.12.1`；
- Windows 标题、左上角、快捷方式、Manifest 和报告一致；
- Mac Core `/api/v1/health.version` 为 `2.3.12.1`；
- Mac Worker 未修改时不重新打包；
- PR 保持 Draft、Open、Unmerged；
- `main` 不修改；
- 正式产物必须有独立 SHA-256、Manifest、安装、VERIFY、故障恢复和回滚证据。

实机验收要求：

1. 创建或选择 approved Handoff；
2. 启动 Mock Dev Broker；
3. Session 依次显示运行并最终 `completed`；
4. Return 显示 `contract_validated`；
5. Provider 为 `local-mock-dev-broker`；
6. changed file 为 1，事件为 4；
7. 刷新后 Session 与 Return 预览不消失；
8. 任务中心没有真实 Provider、项目构建或自动 Git 操作；
9. 取消测试显示 `cancelled` 且没有残留子进程。
