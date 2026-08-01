# Picotoo Pet Connector Contract v1 冻结设计规格

- 文档状态：**Approved / Frozen**
- 冻结日期：2026-08-01
- 合同版本：`1.0.0`
- 实施阶段：Phase 3
- Phase 2.3 交付：Schema、fixture、兼容测试与 Control Center 能力占位
- 非目标：在 Phase 2.3 实现 Maotai、视频助手或任何生产 Connector

## 1. 目的

Connector Contract v1 是所有业务来源接入 Picotoo Pet 的唯一标准边界。它统一项目发现、Artifact 描述、事件去重、目录生命周期、受控写回、错误隔离和 Protected Gate，避免为每个业务程序分别建立一套 AI 后端。

Connector 只做适配与受控副作用，不承载 Agent 规划、业务推理或 GPU 执行。

## 2. 强制原则

1. 原始输入只读；
2. 正式业务数据不得静默覆盖；
3. 事件和写回都必须幂等；
4. 路径先 canonicalize，再验证允许根；
5. 拒绝 symlink、junction、reparse point 逃逸；
6. 单项目失败不得阻塞整个 Connector；
7. processing 中任务必须可通过 lease/heartbeat 回收；
8. 未知外部副作用不得直接重跑；
9. Schema 向后兼容演进；
10. 日志、事件和错误报告不得包含秘密或 Protected 原文。

## 3. 目录生命周期

文件型 Connector 使用以下状态目录：

```text
inbox/
ready/
processing/
output/
errors/
archive/
```

语义：

- `inbox`：外部来源投递区；Connector 仅观察，不在未稳定时读取；
- `ready`：已通过稳定性、完整性和基础 Schema 检查；
- `processing`：已领取并拥有 lease；
- `output`：允许的派生结果或写回包；
- `errors`：隔离失败项目和机器/人可读报告；
- `archive`：成功完成的事件副本或不可变索引；
- 原始输入不因成功或失败被覆盖；是否移动由具体 Connector 策略决定，默认复制元数据、保持原件不变。

## 4. 核心实体

### 4.1 ConnectorEvent

必需字段：

- `schema_version: string`
- `event_id: string`
- `connector_id: string`
- `source_type: string`
- `source_project_id: string`
- `source_revision: string`
- `event_type: string`
- `occurred_at: datetime`
- `discovered_at: datetime`
- `project: ProjectManifest`
- `artifacts: ArtifactManifest[]`
- `idempotency_key: string`
- `permission_tags: string[]`
- `metadata: object`

约束：

- `event_id` 在 Connector 内永久唯一；
- 去重主键为 `connector_id + event_id + source_revision`；
- 同一 `idempotency_key` 的重复提交返回既有接收结果；
- `metadata` 只允许非敏感扩展字段；
- 未知字段可忽略，未知必需语义通过 major 版本升级。

### 4.2 ProjectManifest

必需字段：

- `project_id: string | null`
- `source_connector: string`
- `source_project_id: string`
- `revision: string`
- `title: string`
- `project_type: string`
- `status: string`
- `protected_level: string`
- `source_uri: string`
- `created_at: datetime | null`
- `updated_at: datetime`
- `attributes: object`

约束：

- `source_uri` 是来源标识，不保证可直接作为本地路径打开；
- `protected_level` 至少支持 `public | internal | confidential | protected`；
- `attributes` 不得包含 Token、密码、会话或 Protected 正文。

### 4.3 ArtifactManifest

必需字段：

- `artifact_id: string`
- `project_id: string | null`
- `role: string`
- `uri: string`
- `sha256: string`
- `size: integer`
- `mime_type: string`
- `source_artifact_id: string | null`
- `source_revision: string`
- `time_range: object | null`
- `version: string`
- `permission_tags: string[]`
- `created_at: datetime`

约束：

- `sha256` 使用小写十六进制；
- 文件读取前复核大小和哈希；
- `uri` 必须通过 Connector 自己的允许根验证；
- 派生 Artifact 必须保留 `source_artifact_id` 或明确 provenance 链；
- 任何变化产生新版本，不原地覆盖已归档 Artifact。

### 4.4 WritebackRequest

必需字段：

- `schema_version: string`
- `writeback_id: string`
- `connector_id: string`
- `project_id: string`
- `target_type: string`
- `target_uri: string`
- `action: string`
- `artifacts: ArtifactManifest[]`
- `expected_source_revision: string`
- `idempotency_key: string`
- `request_digest: string`
- `approval_ref: string | null`
- `requested_at: datetime`
- `expires_at: datetime | null`

约束：

- `request_digest` 绑定目标、动作、Artifact 哈希、revision 和权限；
- 目标或文件清单变化后旧批准失效；
- `expected_source_revision` 不匹配时返回冲突，不覆盖新数据；
- L3/L4 动作必须有有效 `approval_ref`；
- 同一幂等键不得重复产生副作用。

### 4.5 WritebackResult

必需字段：

- `schema_version: string`
- `writeback_id: string`
- `connector_id: string`
- `state: string`
- `result_code: string`
- `target_revision: string | null`
- `written_artifacts: ArtifactManifest[]`
- `started_at: datetime`
- `completed_at: datetime | null`
- `trace_id: string`
- `audit_ref: string`
- `error: ConnectorError | null`

允许状态：

`accepted | validating | writing | completed | conflict | rejected | failed_retryable | failed_terminal | unknown_side_effect`

`unknown_side_effect` 禁止自动重试，必须人工检查。

### 4.6 ConnectorError

必需字段：

- `code: string`
- `stage: string`
- `summary: string`
- `impact: string`
- `retryable: boolean`
- `automatic_action: string | null`
- `suggested_actions: string[]`
- `trace_id: string`
- `details_ref: string | null`

错误正文不得包含秘密、完整绝对路径或 Protected 内容。

## 5. Connector 状态与健康

Connector 运行状态：

`not_configured | starting | healthy | degraded | paused | offline | failed`

健康快照字段：

- `connector_id`
- `connector_type`
- `schema_version`
- `state`
- `cursor`
- `last_event_at`
- `last_success_at`
- `heartbeat_at`
- `backlog`
- `processing_count`
- `failure_rate_window`
- `lease_expired_count`
- `user_impact`
- `recommended_action`
- `trace_id`

Control Center 只显示真实健康；未实现 Connector 显示 `not_configured`。

## 6. Lease、恢复与幂等

### 6.1 Lease

processing 记录至少包含：

- `lease_id`
- `owner_id`
- `acquired_at`
- `heartbeat_at`
- `expires_at`
- `attempt`

lease 过期后：

- 未产生外部副作用的步骤可重新领取；
- 已确认幂等副作用可使用同一键恢复；
- 副作用未知时进入 `unknown_side_effect`，不得自动重跑。

### 6.2 幂等

- 事件接收：`connector_id + event_id + source_revision`；
- 项目更新：`source_project_id + source_revision`；
- 写回：`connector_id + idempotency_key + request_digest`；
- 同键同 digest 返回既有结果；
- 同键不同 digest 返回明确冲突。

## 7. Protected Gate

权限级别：

- L0 只读：自动允许；
- L1 派生写入：白名单目标自动允许并审计；
- L2 业务写回：按 Connector 策略，必要时审批；
- L3 Protected/破坏性：默认拒绝，显式审批和备份；
- L4 云端/发布/显著费用：每次人工批准。

路径检查顺序：

1. 拒绝空路径、设备路径和非本地协议；
2. 规范化绝对路径；
3. 解析并拒绝 symlink/junction/reparse point 逃逸；
4. 验证允许根；
5. 验证文件类型、大小、哈希和 revision；
6. 验证动作权限和审批；
7. 写入临时目标；
8. 校验后原子提交；
9. 追加审计。

## 8. Schema 演进

- 使用语义版本；
- patch：文档、约束说明或非语义修正；
- minor：新增可选字段、枚举值或兼容事件；
- major：删除字段、改变含义或新增客户端必须理解的强制语义；
- 接收端忽略未知可选字段；
- 不识别 major 时拒绝并返回 `unsupported_schema_major`；
- fixture 必须覆盖当前版和最近一个兼容 minor 版。

## 9. Control Center 集成

Phase 2.3 只实现：

- `connector_contract_v1` 能力标记；
- Projects/Automation/Health 页面解释性空状态；
- Connector 健康 DTO 和 fixture；
- Project/Artifact 字段的兼容展示模型；
- 不发送生产 Connector 命令。

Phase 3 才实现文件夹 Connector、事件接收、恢复和受控写回。

## 10. 测试门

必须有自动测试证明：

1. 相同事件重复提交不重复建项目或任务；
2. 同幂等键不同 digest 返回冲突；
3. source revision 冲突不覆盖；
4. 原始输入哈希保持不变；
5. 非法路径、链接逃逸和越权写回被拒绝；
6. 单项目错误进入 errors，不阻塞其他项目；
7. lease 过期按副作用状态正确处理；
8. unknown side effect 不自动重跑；
9. 日志和错误不含 Token 或 Protected 原文；
10. Schema minor 向后兼容，major 不识别时明确拒绝；
11. Control Center 对未配置 Connector 显示 `not_configured`。

## 11. 发布与证据

Connector Contract v1 发布物至少包含：

- JSON Schema；
- 正例和反例 fixture；
- 兼容矩阵；
- 哈希清单；
- 自动测试报告；
- 路径安全报告；
- 迁移说明；
- 回滚到前一 minor 的规则。

## 12. 冻结非目标

本合同不规定：

- Maotai 的真实表结构；
- 视频助手的真实目录；
- 具体业务写回目标；
- Worker 执行协议；
- Provider Handoff；
- 云端发布接口。

这些内容在对应阶段通过只读盘点和专用适配规格确定，不得提前猜测或硬编码。

## 13. 冻结状态

本合同作为 Phase 3 的唯一业务接入协议基线。Phase 2.3 只交付 Schema/fixture/兼容能力，不实现生产 Connector。
