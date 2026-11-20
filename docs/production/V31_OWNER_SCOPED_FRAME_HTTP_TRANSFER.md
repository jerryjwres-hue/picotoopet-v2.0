# PicotooPet V3.1｜Owner 一次授权 → Mac 加密下载 → Windows SHA 暂存

**本轮是双机素材网络传输的 CPU-only 组件，仍不是可执行生产任务。**
它接在 #276 Mac 导出 / Windows 内容寻址导入后，使用现有 Core/设备 Bearer，
不新增数据库、独立进程、GPU 调度器或用户必需的操作步骤。

## 两段独立权限（不混淆）

1. **Mac 本机 Owner 操作**：`POST /api/v1/studio/storypacks/owner-review/frame-transfer/issue`
   - 直接复用现有 `ProductionReadinessBody` 的 StoryPack、分镜审核 ID、逐素材使用声明 ID、Episode completion 和整个资产清单。
   - 必须是单独 OwnerPrincipal，通过 `storypack.review`、`asset_use.attest` 的指定主体权限。
   - 即时重新验证分镜未撤销/未过期、全部 Mac Managed 对象真实哈希、声明仍有效、Episode Schema/预算及每镜引用；预期 `source_bindings_sha256` 必须完全匹配。
   - CPU-only 生成含清单与图像的受限 ZIP，并在进程私有临时目录存放最多 120 秒。
   - 返回独立随机一次性 Ticket、ZIP SHA256、来源清单 SHA256，**不产生可复用 GPU/生产授权**。
2. **Windows 设备操作**：`GET /api/v1/studio/frame-transfer/download`
   - 必须有原有 Mac Core 设备 Bearer，同时带仅用于此 ZIP 的
     `X-Picotoo-Transfer-Ticket`；不能仅凭设备令牌列出/抓取所有资产。
   - 网络对端必须为真实 HTTPS，或直接 loopback（CPU 本机测试）；不信任
     `X-Forwarded-Proto`、`X-Forwarded-For` 等伪造代理头。
   - Ticket **领取前即消费**，同时重新检查撤销、期限、Mac 源文件 SHA 及准入上下文。
     重复使用、无效凭据或重新审核后不一致均拒绝下载。
   - Starlette FileResponse 流式发送 ZIP，发送完成后删除服务器临时素材。
   - Windows 的 `fetch_and_stage_frame_bundle()` 用现有已认证 requests.Session
     下载并对照**独立可信来源**给出的预期 ZIP 与 manifest 哈希，然后调用 #276
     的 `stage_frame_bundle()` 在已有 Worker sandbox 中逐图像重新哈希落盘。

## 设备和隐私边界

- 不允许 Windows LAN HTTP 直连此新数据接口；Mac 的既有 :8766 HTTP
  可能对控制命令有效，但**这不表示其承载宠物原始图像已足够安全**。
  真实两机使用前要通过正式验证的 TLS / 安全隧道，并证明请求范围与来源。
- 跨端 Ticket 与 Owner 原始 Token 不保存在 SQLite、日志或 ZIP；
  Core 进程重启后 Ticket 失效。ZIP 不含源绝对路径、Keychain 或用户密钥。
- CPU-only 传输即使成功也必须保持 `can_queue=false` 和 `gpu_authorized=false`；
  现有设备 `POST /episodes`、生产 Plan、Worker Lease/GPU HOLD 均未改动。
- 没有实现 Owner 主人身份的一次性图形配对，也没有把这两次内部调用
  编排进 Studio 按钮；**本 PR 不是完整的自动生产 UI**。
  后续由现有 Core Worker 控制面协调 Ticket，不能让用户人工转发 Owner Token。
- MASTER 版权/商业授权独立核验与 GPU 生产准入仍是独立阻塞项。

## CPU 原生测试

- Owner 有效且完整 StoryPack/asset SHA 正确：下载内容并完成本地图像 SHA 复核。
- 仅设备 Bearer/错误 Owner：拒绝签发；仅 Owner Bearer/错误设备：拒绝下载。
- 已消费 Ticket / 已撤销分镜 / 被篡改 Mac 对象：拒绝；普通远程 HTTP 和代理伪装 HTTPS 拒绝。
- Windows 原生测试继续覆盖 ZIP 篡改、绝对/相对路径、符号链接、重复文件，
  以及导入相同内容时重验并复用。
- 每项流程都核对 `tasks=0`、`production_episodes=0`、`approvals=0`。
