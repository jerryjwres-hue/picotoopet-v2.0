# Phase 10A Handoff 准备与审批设计规格

- 文档状态：**Approved / Frozen for implementation**
- 产品版本：`2.3.10.1`
- 基线版本：`2.3.9.1`
- 合同版本：Handoff / Return Contract `1.0.0`
- 实施范围：Phase 10A 第一条完整垂直切片

## 1. 目标

在不安装、不配置、不调用任何外部 Provider 的前提下，让用户在 Windows 原生 WPF Control Center 中完成：

1. 选择受控 Handoff 模板；
2. 填写任务标题和目标摘要；
3. 由 Mac Core 生成确定性的 Handoff 草稿；
4. 查看脱敏、安全、有界的包预览及 SHA-256 摘要；
5. 把同一摘要提交到现有 Approval Center；
6. 批准后只把 Handoff 状态推进到 `approved`，不启动 Dev Broker、Provider、网络上传或命令执行。

## 2. 不可突破的边界

- PR 保持 Draft，不合并 `main`。
- 用户设备只安装预编译包，不编译源码。
- Mac Core + SQLite 是 Handoff 与审批事实源。
- Windows 仅负责原生 WPF 表单、预览、提交审批和状态观察。
- 不创建 Provider 会话，不下载 Provider，不注入凭据，不上传文件。
- 不创建或编辑真实 worktree；页面展示的是未来隔离目录计划。
- Protected 原件不得进入草稿、预览、审批 scope、日志或 API 响应。
- 不接受任意路径、任意命令、任意仓库地址或任意测试命令。
- `main`、`master`、protected branch、push、merge、tag、release 永久禁止。
- Approval 只绑定精确 `request_digest` 与 `package_digest`；任何内容变化必须重新准备并重新审批。

## 3. 产品范围

### 3.1 受控模板

2.3.10.1 只提供一个内置模板：

`picotoopet-repo-maintenance-v1`

模板固定：

- 仓库：`https://github.com/jerryjwres-hue/picotoopet-v2.0`
- 基线分支：`feature/phase23-slice-d-diagnostic-snapshot-release`
- 基线提交：`5db6b1f9340ff5abe0d38bbb7b6e3ee9b48c34bb`
- Provider：`manual`（仅合同占位，不执行）
- sensitivity：`internal`
- 写入范围：未来 Windows Dev Sandbox 中该 Handoff 独占 worktree
- 固定测试门：Python regression、Windows WPF behavior、Windows formal release、Mac Core arm64
- 固定预算：20 turns、1800 秒、1 并发、无网络工具调用

模板由 Mac Core 提供；Windows 不复制或猜测模板内容。

### 3.2 Handoff 状态

本版本只允许：

`prepared -> waiting_approval -> approved | rejected | expired`

- `prepared`：草稿和摘要已生成，但尚未创建审批；
- `waiting_approval`：最终 manifest 已绑定 approval_id，等待现有 Approval Center 决策；
- `approved`：允许未来 Phase 10B 消费，但本版本不执行；
- `rejected` / `expired`：终态，不允许复用旧审批。

不实现 `staging`、`running`、`returned`、`validating` 或 `ready_for_review`。

## 4. Mac Core 设计

### 4.1 数据库

新增 `handoffs` 表，至少持久化：

- `handoff_id`
- `template_id`
- `title`
- `objective_summary`
- `status`
- `request_digest`
- `package_digest`
- `manifest_json`
- `preview_json`
- `approval_id`
- `created_at`
- `updated_at`
- `expires_at`

数据库迁移必须：

- 从现有 migration 2 安全升级；
- 可重复执行；
- 不修改已有 tasks、approvals、results 数据；
- 在部分升级状态下仍能正确登记 migration 3。

### 4.2 确定性摘要

- 使用 UTF-8、JSON key 排序、紧凑分隔符；
- `request_digest` 绑定模板 ID、标题、目标摘要、Provider、repo/base、权限范围、测试、预算和 expiry；
- `package_digest` 绑定最终安全文件清单及每个派生文件的 SHA-256；
- 标题和目标摘要进行换行规范化、长度限制和控制字符拒绝；
- 同一规范化输入产生相同摘要；
- 内容变化必须产生不同摘要。

### 4.3 安全预览

API 只返回固定字段：

- Handoff ID、状态、模板名称；
- 标题、目标摘要；
- repo/base commit；
- Provider 占位状态；
- sensitivity；
- read/write 路径数量；
- required test 名称；
-预算摘要；
- request/package digest；
- expiry；
- 固定安全边界。

不返回文件正文、Token、凭据、任意本机路径、环境变量、日志正文或未经白名单的 manifest 字段。

### 4.4 审批绑定

扩展 ApprovalService，允许创建 `task_id = null` 的资源审批。审批 scope 只包含固定白名单标量：

- `action=handoff.prepare`
- `handoff_id`
- `template_id`
- `provider`
- `file_count`
- `test_count`
- `budget`
- `target`
- `request_digest`
- `package_digest`

Approval Center 决策完成后，HandoffService 按 approval_id 同步终态。批准不得排队任务或触发其他副作用。

### 4.5 REST API

新增：

- `GET /api/v1/handoffs/templates`
- `GET /api/v1/handoffs?limit=100`
- `POST /api/v1/handoffs/prepare`
- `GET /api/v1/handoffs/{handoff_id}`
- `POST /api/v1/handoffs/{handoff_id}/submit-approval`

创建与提交审批均要求 `Idempotency-Key`。重复请求必须返回同一资源，不得创建重复草稿或重复审批。

## 5. Windows WPF 设计

“云端开发”页从只读合同页升级为 Phase 10A 页面，但保留合同状态和安全边界。

页面分为：

1. **准备表单**：模板只读、任务标题、目标摘要；
2. **安全预览**：固定摘要、状态、digest、测试门和安全边界；
3. **最近 Handoff**：最多 100 条安全记录；
4. **审批动作**：仅当状态为 `prepared` 时显示“提交审批”；提交后提示用户到现有“审批”页处理。

控件必须原生 WPF；不使用 WebView、浏览器 UI、Electron、localhost UI、外部进程或脚本 UI。

用户输入限制：

- 标题 1–120 字符；
- 目标摘要 1–1000 字符；
- 不提供路径、命令、Provider 凭据、仓库 URL、分支或 commit 的自由输入；
- 忙碌期间禁用重复提交；
- 网络错误显示有界消息，不清除已生成预览。

## 6. 测试门

必须先 RED 后 GREEN，并自动证明：

1. migration 3 从旧数据库安全升级且幂等；
2. Protected、路径逃逸、main/master 和控制字符输入被拒绝；
3. 同一输入摘要稳定，任意绑定字段变化摘要变化；
4. prepare 幂等，不产生重复 handoff；
5. submit approval 幂等，不产生重复 approval；
6. 摘要变化使旧审批不能作用于新草稿；
7. 批准只推进 Handoff，不排队任务；
8. API 响应无 Token、路径正文、秘密或任意 JSON；
9. Windows 客户端使用有界响应读取；
10. 真实 STA WPF 页面执行 DataBind、Measure、Arrange、UpdateLayout；
11. 2.3.9.1 的 Results 预览保持、审批中心、任务中心和导航回归继续通过；
12. 原生 Windows Release、Mac Core arm64 及影响检测门通过。

## 7. 发布与版本

- 唯一用户版本更新为 `2.3.10.1`；
- Windows 标题、左上角、快捷方式、Manifest 和报告一致；
- Mac Core `/api/v1/health.version` 为 `2.3.10.1`；
- Mac Worker 未修改时不重新打包；
- 发布物必须包含独立 SHA-256、构建报告、安装/验证/回滚证据；
- 只有用户实机完成准备、预览、提交审批和批准状态观察后，2.3.10.1 才冻结为实机通过。