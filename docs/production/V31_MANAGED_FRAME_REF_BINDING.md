# PicotooPet V3.1｜冻结源码 ID → Windows 可信首帧路径（P0）

## 与现有系统的关系

- Mac StoryPack `first_frame.refs`、`last_frame.refs` 是**受管理资产 ID**，例如
  `maotai_master_v1`。旧版 Windows Bridge 直接把 `refs` 当本地图片路径处理。
- #277–#279 已完成 Owner 一次性下载、内容寻址 ZIP 和 Windows 本地
  `_queue/executor_bridge/staged_references/<sha>.<png|jpg|webp>` 暂存。
- #281 的 Bridge 在本地 GPU inbox 生成前校验已有路径的 SHA，却仍缺少
  `资产 ID → Windows 本地 SHA 文件` 的**实际映射**。
- 本轮复用 `Bridge._jobs()`，不引入第二个本地执行器、数据库或额外服务。

## 本轮新增的可执行数据合同

Mac `inspect_frame_sources()` 的只读输出现在保留完整的
`frame_source_manifest`，其内容与下载 ZIP 内的 `manifest.json` 一致，
并通过 `source_bindings_sha256` 确定性绑定。新字段均**不代表生产授权**。

未来经过**独立 Owner / MASTER / 冻结 Plan 审批**的可信 Core 生产链，
才可以把下列两个字段放进 `gen.keyframe` 任务的 `payload.jobs`：

- `frame_source_manifest`：完整 `picotoo.frame-source-manifest.v1`
  （`storypack_sha256`、`owner_subject_sha256`、所有
  `shot_id/role/asset_ref/managed_sha256` 条目）；
- `source_bindings_sha256`：Core 冻结并持有的规范化源清单 SHA-256，
  **不得从 Windows 或设备客户端的自我声明自动获得权限**。

Bridge 收到此结构后：

1. 精确校验 canonical JSON SHA；拒绝异常字段、重复条目、未知角色、
   跨镜头引用、未声明的资产、镜头条目数量失配和不完整绑定。
2. 根据 Core 指定的资产内容 SHA，在现有 `staged_references` 中只寻找
   `<sha>.png`、`<sha>.jpg`、`<sha>.webp`。缺少或多个扩展名均拒绝，
   绝不猜测文件或按资产 ID 搜索。
3. 复用 #281 的实际文件格式、符号链接、体积上限和流式 SHA 校验；
   在生成本地 `jobs_<task>.json`、`_queue/inbox` 前完成全部检查。
4. 将已有 `jobs.jobs[].refs` 替换为相对 Windows Worker 项目路径，
   删除只供 Bridge 使用的原始清单字段，不向本地模型执行器透传内部证据。
5. 原本没有此清单的 legacy 任务保持默认行为，但 StoryPack Owner
   保护模式下仍由 #280–#281 的 Core GPU HOLD 阻断新租约。

## 本轮尚未实施的最后授权链接

- 目前 `ProductionService.create()` **尚未**从 `production-readiness`
  自动读取清单、更不能把只读检查结果当生产权限。
- 独立 MASTER 来源、动态故事政策、受信任的 Windows 字节回执和冻结
  Plan 的审批仍未完成，因此新清单只是可校验的**执行输入合同**；
  不创建 Episode/Task，不发 GPU Lease，不运行 Comfy。
- 下一项应在**现有生产准入**中先完成 Owner/MASTER 与指定 Job 的授权，
  再以服务端的不可变 Plan 构造这些受管理源条目；
  不能通过直接公开 `POST /tasks` 或恢复旧 lease 来绕行。

## CPU-only 负例

- 跨镜头 ID、错误首/末帧角色、引用重复/多条角色、未声明资产、错误
  manifest SHA、缺失 SHA、缺失本地图片、文件内容改变、文件符号链接；
- 有效单镜头映射会得到唯一的 SHA 对应路径，原始输入保持未修改；
- 不向 GPU 或 Comfy 发送请求，测试实际 Windows 路径解析与文件系统。
