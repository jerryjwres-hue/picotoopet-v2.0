# PicotooPet V3.1 — 本地候选抽卡预算门禁 v1

## 意图

创意规划由云端/本地 LLM 完成，抽卡由 Windows 本地生成。
**一个请求可以包含多个 seeds，但每个 Episode 都必须有有限预算。**
不新增 Windows Worker、调度器、SQLite 表或常驻 Agent。

这轮只实现「新 Episode 创建前的预算预检」，而非 GPU 运行时计时器、
消费金额估算、用户手机操作或自动无限抽卡。已有 GPU HOLD / Owner 安全门禁不变。

## 当前默认额度

| 项目 | 默认 |
| --- | ---: |
| 单镜视频 seeds / 候选数 | 8 |
| 全 Episode 初始视频候选 | 48 |
| 自动 QC 重抽 | 原有最多 2 轮 |
| 预留视频秒数 (含两轮重抽的最坏情况) | 720 |

计算：

    initial_takes         = sum(len(shot.video.seeds) for shot in episode.shots)
    initial_video_seconds = sum(shot.seconds * len(shot.video.seeds) for shot in shots)
    reserve_multiplier    = 1 + MAX_QC_REDO_ROUNDS
    reserved_seconds      = initial_video_seconds * reserve_multiplier

例：3 镜 × 4 秒 × 2 seeds = 首次 6 条候选 / 24 输出秒；
最多两轮 QC 重抽的规划上界是 18 条 / 72 输出秒。
这只是请求的**视频输出秒数**，不是 GPU wall time、active seconds 或电力/成本测量。

同一镜头相同 seed 重复请求会被拒绝，避免无意义的重复本地算力开销。
单次超过预算直接返回 HTTP 422；在发生任何 SQLite Episode、Task 或审计写入前失败。
幂等重放同一份已接收 Episode 不重建任务；内容不同的同 ID 仍按原规则拒绝。

## Core 只读预算预览

在已认证的原 Mac Core API 中：

    POST /api/v1/episodes/budget/preview

请求与 `POST /api/v1/episodes` 一样，接收 JSON 或 YAML 完整 Episode。
响应会返回允许与否、具体错误、初始候选数和最坏情况预留秒数。
**预览不入队、不消耗 GPU、不代表主人授权。**

生产运行配置可由 Mac 管理员使用以下环境变量调整：

    PICOTOO_EPISODE_MAX_TAKES_PER_SHOT=8
    PICOTOO_EPISODE_MAX_TAKES_PER_EPISODE=48
    PICOTOO_EPISODE_MAX_RESERVED_VIDEO_SECONDS=720

配置范围已由 Pydantic 限定。手机网页本身不提供修改额度的接口，
避免浏览器会话增加 GPU 预算。

## 现有抽卡和 QC 关系

- Windows Worker 继续从原文件队列执行现有 `gen.video` 作业；
  只有原本可信的生产授权才能触发 GPU；预算预检本身不放行任何任务。
- 已合并的部分合格 QC 规则保留同批通过的 SHA，失败候选不能被选用。
- 原有 QC 失败最多重新生成两轮；预算按最坏 3 轮预先估计。
- 现有 Episode spec 一旦冻结不可改写，避免用同一 ID 偷换 seeds。
- 高能力 LLM 只负责故事、复杂异常和重要创意决策，普通 seed/评分/QC 不调用 LLM。

## 未完成和后续阶段

1. 真实 Windows 每条生成的 GPU active time 和磁盘消耗须使用 Worker 真实遥测，
   不能将计划视频秒数伪装成 GPU 时间。
2. 允许用户按镜头在手机上提交新抽卡批次，需要可撤销的 OwnerPrincipal 授权，
   精确输入 SHA、预算、并发上限、任务幂等和生产版本控制。本版**不开放**。
3. 用户手动发起更多**有限**批次可以支持近乎无限的累计抽卡，
   但绝不能无预算无限重试或绕开 GPU HOLD。
4. 单次请求在 Worker 上的实际最多输出数量、渲染耗时/超时、磁盘上限，
   仍需另行做实机约束与回归；本轮的校验是 Mac Core 创建前的计划上限。

**验收：** Mac Python/WPF/Windows CI 通过；超过预算在 DB 里 Task=0、
Episode=0、Audit=0；合法作业依旧遵循原生产链和许可机制。
