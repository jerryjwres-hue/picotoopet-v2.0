# PicotooPet V3.1｜Owner 模式旧 GPU 入口隔离（P0 安全修复）

## 实际发现的问题

旧版设备 Bearer 目前可经 `POST /api/v1/episodes` 创建真实 `GPU_TAG` 任务，
也可经 `POST /api/v1/tasks` 直接创建 `gen.keyframe`、`gen.video`
等执行器任务；`POST /api/v1/tasks/{id}/retry` 和剧集合成同样会创建新任务。
这些入口最初用于 legacy episode.yaml，**尚未接入**新版 StoryPack Owner 主体、
独立 MASTER 权利、首帧 SHA + Windows 字节回执、冻结 Plan 及 GPU HOLD。

如果把通过 StoryPack 预检或已同步文件误当成生产许可，这些旧入口会造成绕过。

## 本轮最小 fail-closed 机制

当 **AppSettings.owner_review_registry.credentials 首次出现任意配置项**时，
Mac Core 在启动期间把单例 `owner_production_hold` 标记原子写入现有 SQLite。
从此只要继续使用该数据库，不论当前 Owner 凭据是否过期、禁用或被清空，
旧 GPU 路径都必须保持关闭。单纯删除 Owner Registry 无法降级到 legacy 模式：

- 直接 `POST /episodes`、`POST /episodes/{episode_id}/assemble`：返回
  `409 STORYPACK_PRODUCTION_ADMISSION_REQUIRED`。
- 直接 `POST /tasks` 创建任何 `TASK_RUNNERS` 或 GPU_TAG 任务：同样阻止；
  对已经失败/取消的相关 GPU 任务的 `POST /tasks/{task_id}/retry` 也拒绝。
- 旧 `POST /artifacts/{artifact_id}/decision` 的 `redo` 和
  `accept_qc_failure=true` 可能创建重抽或释放旧下游 GPU 作业，因此也返回 409；
  普通 `pick` / `reject` 的人工记录保留。
- `POST /executors/lease` 在这种模式下**不发放新的任务租约**，返回 204；
  唯一例外为 Worker 明确携带 `resume_task_id`，且数据库中仍为同 Worker、
  同资源标签、RUNNING 且租约未过期的既有任务：只读返回原任务。
  这个例外不触发恢复过期任务、不递增 attempt、不会产生新 GPU POST。
- 原有只读查看、预算预览、普通 CPU 任务、取消旧任务、有效租约的心跳
  和成果回执仍按原逻辑运行，方便人工审查与保留历史。
- **凭据消失不是安全放行信号。** 保护标记使用数据库迁移 v4 创建的
  单例表，首次启用即持久化，重复启动不覆盖时间戳。Owner 凭据文件被误删、
  替换成空配置、禁用或过期都不会恢复旧 GPU 入口。启动初始化失败必须停止服务。
- **不可用数据库回滚冒充正常恢复。** 删除/替换整份 `core.db`、恢复首次启用
  Owner 之前的备份，或人为修改 SQLite，可以丢失此锁；这属于本机文件系统/恢复
  权限问题。正式 V3.1 安装仍要验证带 Owner 的部署身份和备份恢复流程。
  暂时不增加第二个哨兵文件或并行授权系统。
- 没有改原 Worker、Journal 内容、GPU 执行器、已有租约数据库结构或生产模型。
  不修改任何用户设备和 ComfyUI，CPU 测试不发 GPU POST。

## 安全边界与待实施项

1. 这不是新的生产放行机制，**没有**签发任何有效 GPU 授权。
   数据同步的 `CanQueue=false/GpuAuthorized=false` 仍必须保持原义。
2. 这次保护的是**任何曾在当前 Core 数据库启用 Owner Registry** 的旧 HTTP
   入口。一直没有 Owner 配置/历史标记的旧安装仍按原 legacy API 工作，
   避免悄悄破坏已有部署。正式 V3.1 安装必须首次安全配置 Owner 凭据，
   并验证恢复备份时不会把已受保护项目降级回全开放的历史数据库。
3. 下一项才是完成独立的受信任生产 Plan：Owner+MASTER 来源证据、
   镜头/视频预算、Windows 实际素材 SHA、不可变 Plan Digest、
   指定 Job 受控 GPU HOLD/租约恢复与可撤销授权必须原子校验。
   只有这条链验收后才能讨论一次放行。
4. 手机仍只读、没有提交视频的默认权限。不可用手机设备 Token 代替 OwnerPrincipal。
5. 项目本次并未作真实三镜头 GPU 验收，也不能声称已达到第一集画面质量指标。

## 验收

合成 CPU-only 集成测试验证：

- Owner credentials 已启用、禁用、过期三种状态均不能通过旧入口创建 GPU 工作。
- 一般 CPU 任务仍可创建、取消、重试；预算预览只读。
- 新 Worker 租约始终 204，不触发 Queue/Lease 写入。
- 既有未过期运行租约只能由原 Worker+原 ID 恢复；伪造 Worker、错误资源标签、
  过期后重播皆拒绝，不增加 attempt，也不丢弃已有 Journal。
- 没有 Owner Registry 的 legacy 模式仍可使用原始 Episode 创建 API；
  测试严格区分这个兼容模式，不将其当作受保护生产。


### SQLite v4 保护迁移验收

- 原有 `core.db` 自动迁移 v4，只增加单例 `owner_production_hold` 表，不修改
  `tasks`、`production_episodes`、`approvals` 或 Journal 行。
- 新的无 Owner legacy 安装表为空，仍按现有旧模式运行；**仅当首次配置过 Owner
  凭据**才原子插入 `hold_id=1`。
- 关闭 Core 并重新启动、清空 Owner Registry、再次重启：只读报告的保护状态
  与原始 `activated_at` 保持不变，所有旧 GPU 入口仍返回拒绝。
- 将历史非 Owner SQLite 升级至 Owner 模式：旧 Episode 和任务不删除，新的
  GPU POST 与新 lease 被拒绝；原有 RUNNING Journal 恢复规则不变。
