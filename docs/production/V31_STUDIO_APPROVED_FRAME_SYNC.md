# PicotooPet V3.1｜Studio 一键同步已审核首帧（CPU-only 候选）

## 解决的操作缺口

此前 #277 已实现 Owner 本机签发一次性 Ticket、Windows 设备通过 HTTPS 下载 ZIP，
#278 将 ZIP 下载与 SHA 暂存改为原生自包含 .NET 模块，交付在已有 Windows Studio EXE 内。
但 Ticket 和两个 SHA 仍需从 Owner 操作传给 Windows 客户端，用户无法单击完成。

本轮复用上述组件，不再增加其他服务、数据库或审批系统：

1. Mac Owner 在 **Mac 本机受限审核接口** 签发某集已经验证的素材传输申请，
   源文件、主人审计、逐素材使用声明和 Episode 摘要继续按旧合同核验。
2. Mac Core 的同一个进程内新增 `POST /api/v1/studio/frame-transfer/claim`：
   只有已经配对且成功通过原有 device Bearer 的设备才能领取**唯一未领取**的 Ticket。
   操作前再次检查审批和实际 Mac 受管理字节；撤销/过期后直接 409，没任务则 204。
3. Windows 现有 `MacCoreClient.ClaimAndStagePendingFramesAsync(workerRoot)`
   一次性完成 Claim → ZIP 下载 → bundle SHA → manifest SHA → 图片 SHA → 本机目录暂存。
   数据回执必须 `CanQueue=false`、`GpuAuthorized=false`。
4. Studio 的“生产审片”页显示“选择视频目录（首次）”和“同步已审核首帧”。
   项目目录保存到原有非敏感设置，重连 Mac 后仍保留；必须是已有 Worker 项目目录
   （包含 `_queue` 或 `17_静态首帧板V2`），不允许任意路径。
5. UI 直接提示“暂无已审核素材”或“已核对 N 项镜头素材”，不显示 Token、SHA、
   私密素材路径，也不要求运行 PowerShell、Python 或手动传 ZIP。

## 安全门禁与诚实限制

- Owner 的签发仍**只限 Mac 直接 loopback**，目前不是 Windows Studio 代替主人审核。
  因而此按钮只能同步 **已经**经过主人授权的素材；正式 Owner 初次配对/安全审核 UI
  仍需接线，不能把设备 Bearer 升级为 Owner Token。
- 远程 Mac→Windows 素材 GET 和 Claim 都要求**真实 HTTPS**；旧的局域网
  `http://192.168...` 连接即使能进行普通控制指令，也**不能**用于私有图片同步。
  正式安装前还必须验证可信 TLS 双机通道；不允许关闭证书验证或相信代理伪造头。
- 此流程只保证数据一致，不保证 MASTER 法律来源、商用授权、首帧内容语义、冻结生产
  Plan、GPU HOLD 已放行或画面质量。不会调用 `POST /episodes` 或 Comfy。
- 当前 Owner 还需要 Mac 本机安全签发，Windows 视频项目首次还要选一次根目录；
  这些不等同完整零操作自动故事生成。
- 暂存后正式 Worker 消费时仍必须重新验证冻结 Plan 和 Windows 真实字节哈希；
  不应把本阶段成功回执当作可执行生产任务。
- 不签名、不自动合并 main、不操作用户双机或用户现有模型和数据库。

## 原生验证

- Mac Python TestClient：未签发返回 204、只允许 device Bearer、只能领取一次、
  素材撤销后 409、HTTP LAN 被拒、先领后下载并防重放、零 Task/Production Episode。
- .NET Desktop Core SmokeTests：Studio 客户端先 POST Claim 再 GET 下载、SHA 真实落盘、
  再领取返回无数据、非 HTTPS LAN 在网络请求前被拒。
- Windows WPF 和发布构建确保页面按钮与原生方法真实编译入 EXE。
- Mac 及 Windows CI 全绿仍不等于用户双机 HTTPS 或 3×4 秒 GPU 实机成片验收。
