# V3.1｜Windows Studio 实际素材暂存 → Mac 冻结 Plan 数据回执

## 真正减少人工操作的新增接线

沿用现有 Windows Studio **同步已审核素材** 按钮；无需用户输入 Episode ID、Plan SHA 或 Windows 路径。

1. Mac Owner 原有 `frame-transfer/issue` 将 Owner 所选 **Episode ID** 与一次性下载 Ticket 同时传给 Windows（仅数据身份，**不是生产授权**）。
2. 现有 .NET `FrameBundleStager` 逐图片落盘、复核 SHA-256、检查 symlink/归档/图片格式，得到 `FrameStagingReceipt`。
3. Windows 自动提交 `POST /api/v1/studio/frame-transfer/staging-report`，只含 Episode ID、来源 manifest SHA、逐镜头 ID/角色/资产 SHA 及已核验字节数；**不发送私有绝对路径或 Owner Token**。
4. Mac Core **不信任设备提交的 Plan**：从已经存在的 `episode.freeze_owner_hold` 审计重建 Plan SHA，从 SQLite 现有 `gen.keyframe` 任务取得 canonical 来源 manifest，逐项比对并重验 Mac 管理素材的真实字节，最后只写 `episode.windows_staging_report` 审计事件。
5. 如 Owner 尚未冻结指定 Episode，返回 `STAGED_DATA_NOT_YET_FROZEN`、不创建关联审计。用户无需重做审核，但当前并无自动重放已暂存回执；后续放行前必须再次实机核验 Windows 字节。

## 边界

**本回执只有已配对 Windows Studio 的数据上报可信度**。Mac 无法直接读取 Windows 磁盘，也没有收到独立 Worker 执行身份签名，因此 **不能被当作可立即放行的 Worker attestation**。必须在最后 GPU Lease 前让现有 Worker 重新核验实际本地 SHA、冻结 Plan、独立 MASTER 审核/撤销、预期 Task 与 attempt。

每份响应均 `can_lease=false`、`gpu_authorized=false`、`worker_independently_verified=false`。受保护 Owner 模式保持全部新 GPU Lease = HTTP 204，旧 Journal 不得绕行。

此次变更没有安装新插件、新建 Worker/Queue/DB、下载模型、提交 Comfy POST、操作实机或合并 main。测试仅使用合成素材和原生 CPU CI。
