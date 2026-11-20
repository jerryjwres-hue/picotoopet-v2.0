# V3.1｜一个按钮背后的生产准入检查（无 GPU）

**用户操作目标：** Studio 显示“检查是否可以开始生成”；点击一次，仅返回完整的阻塞原因。
后台重读 StoryPack、Owner 审批、素材声明与 Episode 参数，不要求用户填写任何 SHA 或 JSON。

## 现有接口复用

`POST /api/v1/studio/storypacks/owner-review/production-readiness`

- 与原 Owner 分镜审核同一个 Loopback-only 路由、独立 OwnerPrincipal；必须同时持有 `storypack.review` 和 `asset_use.attest`，普通设备 Bearer 不能调用。
- 使用原有 `StoryboardReviewService.verify` 重核当前 StoryPack + 管理的文件字节 + 审批期限/撤销。
- 使用原有 `AssetUseAttestationService.verify` 重核每个角色、场景、风格资产的声明摘要 + 审批期限/撤销。
- 使用原有 `complete_storypack_episode_preview` 和生产预算规则检查最终 Episode 合同。
- 返回每项 `checks`、稳定的 `blocking_reasons`、候选 Episode 摘要与现有预算报告；不输出 Owner Token、文件路径或完整剧本。
- 本操作严格**无生产任务写入、无审批写入、无网络模型调用、无 Worker/GPU 调用**。

## 必须仍然阻塞的项目

即使上述两份 Owner 证据都仍然有效且 Episode 合同正确，以下也不能从声明自动推导：

1. 独立的 MASTER 版权/使用权/出处证据复核。
2. 每镜真实首帧文件对应已批准 MASTER 的检查。
3. 动态故事与版本策略的最终生产准入。
4. 指定 Job 的 GPU HOLD 独立释放。

因此这个版本只输出 `BLOCKED_PRODUCTION_ADMISSION`、
`can_queue=false`、`can_generate=false`、`gpu_authorized=false`。

**不可接入已有仅设备 Bearer 的 `POST /episodes` 作为快捷生产入口。**
当前这条 API 是审核进度汇总，不签发任何可重用的生产 token、lease 或 Plan。

## 验收

CPU-only 合成测试覆盖：同 StoryPack 双 Owner 审核有效、Episode 编译有效、预算通过；
以及设备 token 被拒、分镜撤销、素材实际字节篡改、镜号变更、超额抽卡；
整套测试确认没有 Task/Episode/旧 approvals 写入。真实用户 Mac、Windows 和 GPU 未参与。

## 后续 UI

首选复用 Studio 原来的生产审核页，将 `blocking_reasons` 渲染成简单中文提示。
唯一按钮名称“检查生成条件”；用户无需手动打开三个独立接口。
Owner 身份的本机安全配对/可撤销会话尚未交付，因此暂不对手机或普通设备开放此检查。
