# Phase 10B-A 本地 Return 验证与隔离设计规格

- 文档状态：**Approved / Frozen for implementation**
- 产品版本：`2.3.11.1`
- 基线版本：`2.3.10.1`
- 合同版本：Handoff / Return Contract `1.0.0`
- 实施范围：Phase 10B 第一条低风险垂直切片

## 1. 目标

在不安装、不配置、不调用任何外部 Provider，也不接收用户任意文件的前提下，建立 Phase 10B 的本地安全底座：

1. Mac Core 登记独立 Dev Broker 沙盒语义根；
2. 对已批准 Handoff 生成一个服务器自有、确定性的零变更 Return 演练包；
3. 验证 Return manifest、文件 SHA-256 覆盖、Handoff digest 绑定、事件顺序和安全报告；
4. 对路径逃逸、符号链接、未声明可执行文件、越界 changed file、摘要不匹配、事件缺口和秘密泄漏执行整体隔离；
5. Windows 原生 WPF 只展示有界 Return 安全投影、验证检查和脱敏事件摘要；
6. 同一 Return 经过列表刷新、网络错误和 ItemsSource 替换后仍保持预览。

本版本证明 Return Contract 与 quarantine 机制可工作，但不执行 Provider、diff、测试命令、worktree 修改或 Git 操作。

## 2. 不可突破的边界

- PR 保持 Draft，不合并 `main`。
- 用户设备只安装预编译包，不编译源码。
- Mac Core + SQLite 是 Handoff、Return 与验证结果的唯一事实源。
- Windows 不接受文件路径、上传、命令、Provider 参数、凭据或仓库地址输入。
- 不读取 Credential Manager、Keychain、SSH、浏览器资料、用户文档或业务原件。
- 不启动外部进程，不创建真实 Provider 会话，不访问公网。
- 不应用 `diff.patch`，不创建或修改真实 worktree。
- 不运行 Return 中声明的命令；Provider 测试报告不作为本地通过证据。
- 不自动 push、PR、merge、tag、release。
- Protected 原件与 Raw Evidence 永久禁止进入 Return 演练包、日志和 API。
- 所有未知字段、未知事件、未知文件和未知可执行内容默认拒绝。

## 3. 产品范围

### 3.1 本地 Return 演练

Windows 只提供一个动作：`运行本地 Return 合同验证`。

动作要求：

- 当前 Handoff 状态必须为 `approved`；
- 使用一次生成并在单次重试中复用的 `Idempotency-Key`；
- Mac Core 使用服务器内置生成器创建固定零变更 Return；
- Return 不包含代码正文、二进制、任意 artifact 或外部会话输出；
- changed file 数量固定为 0；
- 测试报告只标记 `not_run`，不得伪装成本地 CI 通过；
- 成功只表示 `contract_validated`，不表示代码可合并或发布。

### 3.2 Return 状态

本版本 Return 状态只允许：

`received -> validating -> contract_validated | quarantined`

- `received`：服务器内置 Return 已持久化；
- `validating`：正在执行纯结构、哈希、策略和事件验证；
- `contract_validated`：合同完整性通过，但未执行 diff、本地测试或构建；
- `quarantined`：任一安全门失败，保留有界原因，不自动修补或放宽规则。

Handoff 保持原有 Phase 10A 状态。Return 演练不得把 Handoff 推进到 `ready_for_review`。

### 3.3 固定文件集合

内置 Return 只允许：

- `return_manifest.json`
- `session_events.ndjson`
- `summary.md`
- `changed_files.json`
- `test_report.json`
- `build_report.json`
- `security_report.json`
- `questions.md`
- `signatures/manifest.sha256`

`artifacts/` 在本版本必须为空且不得出现在演练包中。

## 4. Mac Core 设计

### 4.1 数据库

新增 migration 4 和 `returns` 表，至少持久化：

- `return_id`
- `handoff_id`
- `status`
- `provider`
- `request_digest`
- `package_digest`
- `manifest_digest`
- `changed_file_count`
- `event_count`
- `validation_checks_json`
- `preview_json`
- `quarantine_code`
- `idempotency_key`
- `created_at`
- `updated_at`

迁移必须可重复执行，并保持 migration 1–3、tasks、approvals、results 和 handoffs 数据不变。

### 4.2 确定性 Return 生成器

内置生成器固定：

- provider：`local-contract-self-test`；
- external session：本地确定性占位，不代表外部会话；
- base commit、request digest 和 package digest 从目标 Handoff 读取；
- changed files：空列表；
- session events：started、progress、returned 三个有序脱敏事件；
- test/build：`not_run`；
- security report：仅报告合同演练已检查的固定项目；
- canonical JSON：UTF-8、排序 key、紧凑分隔符、末尾换行规则固定；
- manifest digest 和文件清单 digest 可重算。

同一 Handoff 和相同幂等键必须返回同一 Return；不同幂等键可生成独立演练记录，但不得改变 Handoff。

### 4.3 验证器

验证器必须执行：

- 总文件数、单文件大小和总大小上限；
- POSIX 相对路径规范化；
- 拒绝绝对路径、盘符、`..`、反斜杠逃逸、NUL 和重复路径；
- 拒绝 symlink/hardlink/device 标记；
- 文件集合与 allowlist 完全匹配；
- `manifest.sha256` 覆盖全部非签名文件且无额外项；
- 每个 SHA-256、manifest digest 和 package digest 可重算；
- handoff_id、request digest、package digest、base commit 与事实源一致；
- provider 为固定本地演练值；
- changed files 必须为空；
- test/build 不得声称 pass；
- 事件 sequence 从 1 连续递增，event_id 唯一，event type 在白名单中；
- 事件 payload 有界并经过秘密模式扫描；
- 任一失败把整个 Return 记为 `quarantined`，只保存固定错误码和安全摘要。

### 4.4 REST API

新增：

- `GET /api/v1/returns?limit=100`
- `GET /api/v1/returns/{return_id}`
- `POST /api/v1/handoffs/{handoff_id}/returns/self-test`

写操作要求 `Idempotency-Key`。API 不接收 multipart、base64 文件、路径、命令或任意 manifest JSON。

API 只返回：

- Return ID、Handoff ID、状态；
- 固定 provider 标签；
- request/package/manifest digest；
- changed file 和事件数量；
- 固定验证检查名称与结果；
- 有界 quarantine code；
- 创建和更新时间；
- 最多 16 条脱敏事件摘要。

不返回文件正文、原始事件 payload、内部包字节、路径列表、环境变量、Token 或日志。

## 5. Windows WPF 设计

“云端开发”页新增 **Phase 10B-A 本地 Return 验证** 区域：

- 仅当选中 Handoff 为 `approved` 时启用演练；
- 显示最近 Return 记录和固定安全预览；
- 显示 `contract_validated` 与“未运行代码/测试/Provider”的明确说明；
- 显示 manifest digest、事件数、changed file 数和验证检查；
- 不显示文件正文、路径、原始日志或终端输出；
- 不提供文件选择器、拖放、路径框、命令框、Provider 或凭据输入；
- 刷新失败不得清除已有 Return 预览；
- 同一 `return_id` 刷新后复用逻辑选择并保持预览。

页面继续保留 Phase 10A Handoff 准备与审批功能。

## 6. 测试门

必须先 RED 后 GREEN，并自动证明：

1. migration 4 从 migration 3 安全升级且幂等；
2. 未批准、已拒绝或过期 Handoff 不能运行 Return 演练；
3. 相同幂等键只创建一个 Return；
4. 正常内置 Return 的全部 SHA-256、digest 和事件顺序可复验；
5. 路径逃逸、绝对路径、重复路径、symlink、额外文件和未声明 EXE 被隔离；
6. request/package digest、base commit 或 handoff_id 不匹配被隔离；
7. 越界 changed file、二进制、事件缺口、重复 event_id 和未知事件被隔离；
8. Token、Authorization、密码和 Protected 内容不能进入事件或安全预览；
9. Provider 声称 tests passed 被隔离，`not_run` 才能通过本切片；
10. API 无文件上传、任意路径、任意 JSON 或内部包内容；
11. Windows typed client 使用有界响应读取和同一幂等键单次重试；
12. 真实 STA WPF 执行 DataBind、Measure、Arrange、UpdateLayout；
13. Return 预览在 ItemsSource 替换和有界网络错误后保持；
14. 2.3.10.1 的 Handoff、审批、Results 预览、任务中心和导航回归继续通过；
15. Windows 正式 Release、Windows WPF、Mac Core arm64 和 Worker 影响检测通过。

## 7. 发布与版本

- 唯一用户版本更新为 `2.3.11.1`；
- Windows 标题、左上角、快捷方式、Manifest 和报告一致；
- Mac Core `/api/v1/health.version` 为 `2.3.11.1`；
- Mac Worker 未修改时不重新打包；
- 发布物包含独立 SHA-256、构建、安装、验证和回滚证据；
- 只有用户实机完成 approved Handoff 的本地 Return 演练并确认 `contract_validated` 后，2.3.11.1 才冻结为实机通过。
