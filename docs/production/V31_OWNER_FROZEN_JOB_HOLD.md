# PicotooPet V3.1｜Owner 冻结指定 Production Job（仍处 GPU HOLD）

## 本轮实际可执行入口

`POST /api/v1/studio/storypacks/owner-review/production-freeze`

此接口需要 Mac **直接 loopback** 上独立 Owner Bearer（不是设备令牌）。
正文复用现有 `ProductionReadinessBody`，另含三个必需字段：

- `expected_candidate_episode_sha256`：先前只读预览返回的最终 Episode SHA；
- `expected_source_bindings_sha256`：与 ZIP `manifest.json` 一致的来源清单 SHA；
- `confirm_gpu_hold: true`：明确同意仅建立冻结任务，不开启 GPU。

Core 在每次写入前重新核验：当前 Owner `storypack.review`、
`asset_use.attest` 双作用域、不可撤销/未过期的分镜审核、资产使用声明、
实际 Mac managed object 文件内容、Episode 合同、GPU 最坏重抽预算及
所有镜头素材 ID、SHA 绑定。任何一项变更会拒绝创建任务。

然后生成一份不可变 `picotoo.owner-frozen-plan.v1`，其 SHA 绑定：

- 精确 `subject_key`、Owner `actor_id` 与 registry revision；
- `storyboard_review_id`、`asset_attestation_id`；
- StoryPack / Episode 完整摘要、来源清单完整摘要。

通过**原有 `ProductionService.create()` 和 `queue._create_in_transaction()`**
在**同一 SQLite 事务**中写入该 Episode 的 `gen.keyframe`、
`gen.video`、`gen.foley` Task 及新审计事件
`episode.freeze_owner_hold`。其中 keyframe 任务携带 #282 已验证的
ID/SHA 绑定，供未来执行时的 Windows Bridge 重验并转换路径。

相同 Episode ID + 完整 Plan SHA 允许幂等重试；任意 Episode、来源、
Owner 审核或资产使用声明变化均不得复用既有任务。

## 严格 HOLD 边界

- Core Task 行确实已写入 SQLite，内部状态仍可能显示 `Queued`，
  但 Owner 持久安全锁使 `POST /executors/lease` **始终返回 204**，
  心跳和旧 Journal 不得绕过，无法产生新的 GPU POST。
- 回执必须返回 `FROZEN_OWNER_INTENT_AWAITING_INDEPENDENT_ADMISSION`，
  `can_lease=false`、`can_generate=false`、`gpu_authorized=false`，
  不能把 `Queued` 与获批执行混为一谈。
- 资产使用声明是 Owner 自述，**不是**独立 MASTER 法律/许可证审查；
  当前没有启用相关独立授权、动态故事政策或 GPU HOLD 释放。
- Windows 下载阶段的 SHA 回执并不自动等于冻结生产 Plan 的执行准入。
  未来仍须绑定实际 Worker、特定 Job/Task/attempt、MASTER/素材、
  冻结 Plan SHA 和吊销机制后才能谈受控放行。
- 冻结时检查与 SQLite 插入之间，外部管理文件理论上仍可能变化，
  所以最终任务放行必须再次重验最新 Owner 审计和原始素材/Worker 字节。
  不能因为本次冻结成功就跳过独立的最终准入。
- 暂未改原 Worker 调度器、现有 UI 的普通设备 API、GPU HOLD 或模型执行。
  未操作用户双机，没有任何真实 Comfy POST。

## Native CPU-only 合成验收

- 两个镜头的合成 StoryPack 先通过原 Owner/Asset 审核，后由真实
  `production-freeze` 生成 6 条 Core Task、1 条 `FROZEN_HOLD` 审计；
- 完整审计 Plan SHA、逐 Task shot_id、无审批表放行，租约始终 204；
- 相同 Plan 幂等返回相同 Task ID，不能重复计费/入队；
- 错误 Episode SHA、来源 SHA、预算超额、已撤销分镜/素材声明、
  Mac 源文件篡改、设备 Bearer、远程 HTTP、拒绝 confirm GPU HOLD 都 fail-closed。
- 保护模式和旧 Worker 恢复规则保持不变，所有测试只使用合成图片。
