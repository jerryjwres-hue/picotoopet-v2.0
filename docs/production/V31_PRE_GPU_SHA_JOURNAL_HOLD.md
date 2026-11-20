# PicotooPet V3.1 P0｜Worker 提交前素材哈希与历史 Journal HOLD

这是 #280 之后的**最小补丁**，继续使用现有 Windows Bridge、Mac Core
HTTP、SQLite 租约和本地 Journal，不引入第三套执行器。

## 发现的两个真实风险

1. **已暂存素材会变更**：#276–#279 可以验证 Windows 在下载时收到的素材
   与 Mac 的 SHA 一致，但旧 `Bridge._jobs()` 仅调用 `_safe_path()`
   防止越出项目目录，没有在创建真正的本地 `_queue/inbox` 前重读
   `staged_references` 文件 SHA。文件在同步后遭到修改会浪费 GPU。
2. **旧 RUNNING 不等于已 POST**：#280 曾允许同 Worker 有效
   `resume_task_id` 返回 RUNNING 任务，也允许其心跳。
   这只证明 Core 发过租约，**不证明** Windows 已将任务送到 GPU。
   旧 Journal 的 `submitted=false` 在重新连接时仍可能自行 POST，
   因此此前“read-only resume 永不重新 POST”的保证不充分。

## 本轮改动

- Windows 原有 Bridge 在 `_jobs()` 解析每条参考图的 `refs` 和 `mask`
  时，如果路径位于已知的
  `_queue/executor_bridge/staged_references`，要求目标文件以
  `<64位小写SHA256>.png|jpg|webp` 命名，并重新打开真实文件、
  排除 symlink、检查图像魔数和 ≤64 MiB 大小、流式 SHA-256 对账。
- 对不属于内容寻址暂存目录的原有合法 legacy 路径保持原行为。
  同一个 Job 内重复引用相同文件只做一次 SHA 计算。
- 检查失败时在产生任何新 `_queue/inbox/*.json` 及 `jobs_*.json`
  之前报错，保留审计信息和现有报告流程；从未以文件名或旧收据
  代替当次校验。
- Mac Core 在 SQLite Owner HOLD 已经启用时，
  `POST /executors/lease` 对任何新任务**及旧任务 resume**返回 204；
  GPU 任务的 `POST /tasks/{id}/heartbeat` 返回 409。
  旧 Worker 因此不会在仅有 RUNNING 租约、没有已提交证据的情况下
  把任务重新 POST 到本地 inbox。
- 原始 SQLite Task 与 Windows Journal 都不删除；
  `complete/fail` 对已经记录在 Journal 的提交报告仍执行原有
  Worker ID / attempt / 有效租约校验。

## 明确的取舍

- Owner HOLD 下不再自动重启旧 RUNNING GPU 作业。已经送到 GPU
  但尚未收取回执的旧 Journal 可能需要只读现场核对，
  不能为了自动恢复而把未经证实的任务重新提交 GPU。
- 这并非完整的“指定 Job 受控放行”；
  独立 MASTER 法律来源、正式 Owner/冻结 Plan、
  Windows 实际来源绑定及签名 GPU 授权仍然是正式放行前提。
- 不能把现在的 MAC/Windows 合成 CI 当作真实 5070 Ti 视频验收。
- 文件哈希是提交前校验，不能替代未来逐 Job 固定素材副本及
  真正受信任的 Worker/Comfy 执行许可。
- 无真实设备操作、无模型下载、无 Comfy POST、无生产任务写入。

## CPU-only 验证

- 合成 PNG 有效 SHA、提交前文件篡改、非法文件名、目录 symlink、
  传统相对路径兼容性、坏图零写 inbox 和 `jobs_*.json`。
- 旧 Journal `submitted=false` 收到 Core 心跳 409、租约 204 时，
  保留 Journal，零新 inbox/任务提交；Mac 原生 API 测试验证
  正在运行且仍有效的旧租约也不能继续 heartbeat/resume。
