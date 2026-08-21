# PVP Director Console Native v2 N6E3 导演体验修正设计

## 目标
在不改变 `PVP-DIRECTOR-CONSOLE-NATIVE-V2.0-FREEZE-1` 数据/治理/执行边界的前提下，修正四个已在实机确认的使用问题：中文化不足、Director Core 连接不稳定且依赖人工重连、默认界面过度暴露开发术语、删除入口隐蔽且无批量删除/恢复。

## 不变边界
- Canonical Source 继续只读；编辑继续 Proposal / Overlay / Take。
- 删除继续是 soft delete + tombstone；不增加永久清除；ID 不复用。
- AI 不得自主删除；所有删除/恢复写操作 actor 必须是 `HUMAN_DIRECTOR`。
- Director Core 仍是本地 loopback source of truth；Native WPF 不直接访问 ComfyUI 执行端点。
- N6E3 不新增媒体生成端点，不调用 `/prompt` / `queue_prompt`。
- GitHub Windows CI 继续预编译；用户机不执行 dotnet build/publish。

## 1. 中文简洁导演台
默认界面以中文业务含义为主，技术 ID 和英文枚举仅作为灰色辅助信息。顶部只保留连接状态、待审批和刷新；手动 Core 重连移动到“系统/高级”。`Inspector` 改为“高级详情”，`Timeline` 改为“时间线”，二者默认收起；时间线收起时不占固定 170px 空白。

导航组统一中文：前期制作 / 制作 / 剧组 / 系统。状态映射：ACTIVE=进行中，STALE=需复核，BLOCKED=受阻，NEEDS_DIRECTOR=待导演处理，READY=已就绪，DELETED=已删除。底层 JSON/数据库枚举不翻译。

## 2. Director Core Supervisor
Native 进程管理器升级为长期 Supervisor：
- 持续健康检查，而不是只在初始化时启动一次；
- 发现 owned Core 退出时自动重新启动；
- 健康检查失败时按 0.5s/1s/2s/4s/8s 退避恢复；
- 每轮恢复有明确 attempt/status/reason；
- stdout/stderr 落本地 `%LOCALAPPDATA%\PVP\DirectorConsole\logs\director-core-*.log`；
- UI 在恢复期间保持最后一次快照，写操作禁用，读取内容不清空；
- 仅停止带自身 lifecycle token 的 owned Core，不触碰其他 8765 进程。

ViewModel 不再只在 `READY` 状态轮询；后台 Supervisor 持续尝试恢复，成功后自动刷新。顶部显示：正在启动 / 已连接 / 正在恢复 n/5 / 未连接（原因）。

## 3. 单项和批量删除
节点列表上方固定提供“删除”和“批量选择”。批量模式使用每行复选框，支持全选当前、清空、删除选中 N 项。

Backend 新增批量预览和批量执行 API。批量删除在单个 SQLite 事务中完成：
- 先校验全部 node id、revision、不可删除 PROJECT:ROOT、无重复、均未删除；
- 先计算每项影响并聚合；
- 同一事务写所有节点状态、所有 tombstone、一次 revision bump、一次批量 ledger entry；
- 任一项失败则整个事务回滚。

UI 删除确认显示：选中数量、聚合下游影响数量、Canonical 不物理删除、可从“已删除”恢复。

## 4. 批量恢复
“已删除”页面支持多选、全选当前、清空、检查恢复、恢复选中 N 项。Backend 对批量恢复同样使用单一事务：先预览全部 blocker/sequence impact，再统一恢复、一次 revision bump、一次 batch ledger；任一 tombstone 不合法则全部回滚。

## 5. 错误处理与测试
- Backend 使用真实 SQLite 单元测试证明 batch delete/restore 原子性、revision conflict、Human Director 权限、PROJECT:ROOT 禁止删除。
- Native source-contract 测试证明 Supervisor、退避、日志、中文映射、默认高级面板收起、批量动作/DTO/client endpoint 存在。
- GitHub Windows 2025 必须通过：VBS/CMD bootstrap smoke、PowerShell installer parse、Native contracts、WPF build、self-contained publish、EXE self-test。
- 用户实机只验收安装、Core 长期连接和交互，不再承担源码编译。
