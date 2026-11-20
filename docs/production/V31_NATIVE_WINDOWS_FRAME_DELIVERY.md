# PicotooPet V3.1｜Windows Studio 原生素材同步（P0 候选）

## 为什么这一步必要

PR #276/#277 已通过 Mac 导出、Owner 单次 Ticket、HTTPS 下载和 Windows Python CPU 暂存测试。
但 Phase 2 Windows 发布使用单文件、自包含的 .NET 10 Studio EXE；不能让用户另行安装 Python 并调用 `stage_frame_bundle.py`。

本轮直接把内容寻址 ZIP 校验与 Windows 文件落盘实现为当前 `PicotooPet.Desktop.Core` 项目内的 C# 方法，
由现有 WPF Studio 发布过程编译进 `Picotoo Pet AI.exe`，没有第二套安装程序。

## 可供既有 Studio 调度组件调用的方法

`MacCoreClient.DownloadAndStageFramesAsync(ticket, expectedManifestSha, expectedBundleSha, workerRoot, ct)`

- 设备 Bearer 仍由现有 `MacCoreClient` 管理；只使用 Owner 单次 Ticket，不接收 Owner Token。
- 外部传输必须 HTTPS；仅真正 loopback 允许本地 HTTP，禁止 HTTP LAN。
- 正式工厂客户端的控制 HTTP 与素材 HTTP 使用分离的连接池和超时，素材连接池 120 秒、禁止自动跳转。
- 先读取 HTTP 状态和服务端摘要，再流式落地临时 ZIP，限 129 MiB；**以可信 Core/Plan 上下文给定的预期摘要**重算 ZIP SHA。
- `FrameBundleStager.StageAsync` 核验 manifest、逐镜 `shot_id`、`asset_ref`、唯一映射、每张实际图片 SHA、格式魔数和目录边界，限单个 64 MiB / 总计 128 MiB。
- 目标目录仍是旧 Worker 项目里的
  `_queue/executor_bridge/staged_references/<sha256>.<png|jpg|webp>`，
  对重复目标先重读 SHA，采用不覆盖现有文件的原子移动；返回对原 Worker 首帧板有效的相对 ref。
- 回执 `FrameStagingReceipt` 明确 `WorkerLocalBytesVerified=true`、`CanQueue=false`、`GpuAuthorized=false`。

## 用户日常操作不会增加

此版本**仍未提供** Studio 的“自动触发 Owner 发证 → Windows 调用下载”的 UI 接线；
不需要也不应该要求用户手工拷 ZIP、粘贴 SHA、复制 Ticket 或安装 Python。

下一项接线应当复用现有 Studio 的配对/审核组件与正式 Mac Core 调度，
在独立 Owner 授权和冻结 Plan 重新校验后向 Windows 发送仅数据同步的任务，
然后继续按原 Worker GPU HOLD 门禁执行；不得把素材落盘回执直接视为放行许可。

## 验收证据与 STOP

- Windows 原生 `Desktop.Core.SmokeTests` 被原有 Windows 预编译发布流程自动调用。
- 合成图像/ZIP 验证当前 .NET：签名摘要匹配、路径正确、重复导入、篡改阻止、LAN HTTP 拒绝、
  使用设备 Bearer + 一次性 Ticket 下载的兼容性，以及无 GPU 放行。
- Mac Python 原有多镜头合同与跨端 HTTP 测试仍须通过。
- 此版本不启用任何 GPU/Post、Comfy、模型、真实用户机器或生产数据库。
- 还没有可信 TLS 双机实际部署、远程 Owner 配对、独立 MASTER 许可核验、
  生产冻结 Plan 入队、真实三镜头与人工视觉 ACCEPT，因此**不是正式 V3.1 完整版**。
