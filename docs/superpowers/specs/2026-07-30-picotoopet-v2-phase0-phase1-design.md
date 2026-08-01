# Picotoo Pet V2 Phase 0/1 设计规格

## 1. 目标

建立一个全新的 `picotoopet-v2` 仓库，在不修改 V1、Maotai、REAL PET 创作助手和其他 Protected 原始数据的前提下，交付以下能力：

1. Phase 0 只读资产盘点、哈希登记、环境检测与冻结报告。
2. Phase 1 Mac Core：PydanticAI、SQLite 耐久任务队列、Permission Gate、Audit Log、Result Store、MCP Hub、REST API、WebSocket、Ollama Resident Manager、launchd 和 Health Supervisor。
3. Windows ComfyUI 检测与模型引导安装：自动识别 Comfy Desktop、数据目录、Python、API、节点、模型和 GPU；在 `E:\PicotooPet` 下建立模型布局；按冻结顺序下载、校验并配置 Wan2.2 TI2V-5B 与 Wan2.1 VACE-1.3B 等视觉组件。
4. 安装、验证、修复和回滚均提供双击入口；日常运行不要求打开 Terminal、CMD 或 PowerShell。

## 2. 冻结约束

- Mac mini M4 Pro 64GB 是专用本地 AI 服务器。
- Windows 11 设备使用 RTX 5070 Ti 16GB 执行视觉任务。
- `gpt-oss:20b` 是 Mac 默认模型，必须永久常驻并自动恢复。
- Windows 不安装第二份 `gpt-oss:20b`，核心阶段不安装通用 8B LLM。
- Agent Runtime 固定为 PydanticAI；工具接口固定为 MCP Hub；初始耐久队列固定为 SQLite。
- ComfyUI 是 Windows 视觉生成引擎；Wan2.2 TI2V-5B 是主视频生成模型；Wan2.1 VACE-1.3B 是主视频编辑模型。
- Protected 原始数据不得修改、移动、覆盖、删除或直接上传。
- 云端上传必须人工批准。
- V1 只备份，不作为 V2 运行依赖。
- 所有代码注释使用中文，并保持同一代码块中的注释列尽量对齐。

## 3. 系统边界

### 3.1 Mac Core

Mac Core 是唯一的任务事实源和调度中心。它负责：

- 项目、任务、依赖、审批、结果和审计数据的耐久存储。
- PydanticAI Agent 的运行、结果验证和复核。
- MCP 工具注册、权限检查和调用审计。
- REST/WebSocket 对 Windows Desktop 和 Connector 提供状态与控制接口。
- `gpt-oss:20b` 常驻、健康检查和自动重载。
- launchd 开机启动、崩溃重启和夜间任务入口。

### 3.2 Windows Bootstrap

Windows Bootstrap 不替代后续 Phase 2 的 WPF Desktop，也不直接实现 Phase 6 的完整 GPU Worker。它负责：

- 只读发现 Comfy Desktop 程序目录和运行数据目录。
- 检测 `custom_nodes`、模型、工作流、Python、Torch、CUDA、ComfyUI API、显卡和磁盘。
- 在 `E:\PicotooPet\Models`、`E:\PicotooPet\ComfyUI` 和 `E:\PicotooPet\Installers` 建立受控布局。
- 备份后增量更新 `%APPDATA%\ComfyUI\extra_models_config.yaml`，绝不修改 Desktop 的 `resources\ComfyUI`。
- 使用官方 Hugging Face CLI 下载模型，支持断点续传、重复运行和 SHA-256 校验。
- 生成 HTML/JSON 检测与安装报告；失败时不删除已验证模型。

## 4. 数据模型

SQLite 使用 WAL、`foreign_keys=ON`、`synchronous=FULL` 和 `busy_timeout=5000`。

核心表：

- `schema_migrations`
- `projects`
- `artifacts`
- `tasks`
- `task_dependencies`
- `task_attempts`
- `task_events`
- `approvals`
- `results`
- `audit_events`
- `idempotency_keys`
- `device_pairings`
- `service_health`
- `event_outbox`

`task_events`、`audit_events` 和 `event_outbox` 采用追加式语义。`results` 只保存对象哈希和清单；对象文件使用内容寻址目录和原子替换。

## 5. 任务状态机

状态：

`Created → Validating → Queued → Running → WaitingForTool / WaitingForApproval / Retrying / Completed / Failed / Cancelled → Archived`

约束：

- 终态不能回到运行态。
- 重试创建新 attempt，不抹除旧 attempt。
- 运行任务使用租约；租约过期进入 `Retrying`。
- `cloud_manual` 任务必须进入 `WaitingForApproval`。
- `idempotency_key` 返回已有任务；活跃 `dedupe_key` 不重复创建。

## 6. 权限模型

分类：`PUBLIC`、`INTERNAL`、`PROTECTED`。

主体：`human_operator`、`mac_agent`、`mcp_tool`、`windows_device`、`connector`、`health_supervisor`、`cloud_exporter`。

操作：`read`、`create`、`update`、`delete`、`move`、`execute`、`cloud_upload`。

规则：

- 默认拒绝。
- Protected 只允许经明确策略授权的读取；写、删、移动和直接上传始终拒绝。
- 路径先标准化，再检查根目录、符号链接和路径穿越。
- MCP 不暴露任意 Shell 或任意路径读写。
- Approval Token 一次性、限时、限范围并写入审计。

## 7. API 与 MCP 契约

REST 前缀为 `/api/v1`，提供 health、status、capabilities、projects、tasks、results、approvals、pairing 和 audit 端点。WebSocket 为 `/api/v1/events`。

MCP 工具名保持冻结清单，不擅自改名。Phase 1 中，本地读写、报告、状态、审批和 Handoff 工具可执行；Windows 重型工具只创建耐久任务并在 Worker 不在线时返回明确能力状态。

统一错误体：

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "该操作不允许访问 Protected 数据。",
    "retryable": false,
    "trace_id": "..."
  }
}
```

## 8. Ollama 常驻策略

- 启动时调用 `/api/tags` 确认 `gpt-oss:20b` 已安装。
- 调用 `/api/generate`，`stream=false`、空提示、`keep_alive=-1` 预加载。
- 周期调用 `/api/ps` 确认模型仍在运行。
- 丢失时指数退避重载，并记录 health 与 audit。
- 专业模型按需加载；默认不永久常驻。

## 9. Windows 模型清单

第一批基础生产：

- `wan2.2_ti2v_5B_fp16.safetensors`
- `wan2.2_vae.safetensors`
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors`
- faster-whisper 运行环境
- FFmpeg
- RIFE
- Real-ESRGAN

第二批编辑能力：

- `wan2.1_vace_1.3B_fp16.safetensors`
- `wan_2.1_vae.safetensors`
- SAM2
- Depth/Pose/Control 的受控接口

模型必须先下载到临时文件，校验大小和 SHA-256 后原子移动到目标目录。已存在且哈希匹配的文件直接复用；哈希不匹配的文件移入隔离目录，不覆盖原件。

## 10. 测试与验收

- 单元测试：状态机、权限矩阵、路径策略、哈希链、对象存储、幂等和模型清单。
- 集成测试：REST→SQLite→Queue、审批恢复、Outbox→WebSocket、Ollama Mock、MCP 工具注册。
- 故障测试：进程终止、租约过期、SQLite 锁、Ollama 离线、模型卸载、磁盘不足、下载中断。
- 安全测试：Protected 写入/上传拒绝、路径穿越、符号链接逃逸、Token 重放、日志密钥扫描。
- 安装测试：重复安装、验证、修复和回滚。

Phase 1 验收必须证明：Mac 开机自动运行、`gpt-oss:20b` 自动常驻、API/MCP/WebSocket 可用、队列可恢复、Protected 写入被拒绝、普通任务无需批准、云端任务必须批准、结果哈希可验证、日志无明文秘密、安装可回滚。
