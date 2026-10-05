# PicotooPet AI — Superpower v1.0
## 可靠性、进度可视化与本地模型故障诊断完整设计方案

**设计状态：** Proposed / implementation-ready after review  
**工程基线：** `feature/autonomous-intelligence-e2e-goal-center-2.3.27.1`  
**产品公开版本：** `Superpower v1.0`  
**内部工程构建号：** `2.3.27.1+<build>.<sha>`  
**日期：** 2026-08-20

---

## 1. 目标

这一轮不做“把超时调大”式补丁，而是把 Superpower v1.0 的**运行可靠性、可诊断性、可恢复性和进度可视化**一次收口。

必须解决四类问题：

1. **Mac 看起来经常断线**：需要区分是真正网络断线、Windows WebSocket 误判、Worker 状态心跳过期、还是本地模型卡住。
2. **复杂任务像黑盒**：运行时必须持续显示真实阶段、单位进度、最后活动时间、组件健康和降级原因，而不是长期“处理中 / 无结果”。
3. **Ollama / gpt-oss:20b 故障可能拖住任务**：模型可以失败，但 Mac Core、Worker、Workflow、Windows 控制面不能跟着失效。
4. **产品身份混乱**：用户界面统一显示 `PicotooPet AI — Superpower v1.0`；`2.3.x` 只保留为内部工程 Build 信息。

本方案明确保持现有安全边界：Windows 不执行爬虫和 Shell；Mac Core 仍是唯一事实源；Research Gateway 只读；网页 ChatGPT 上传暂时继续人工；茅台 Natural Motion V2 独立，不被本轮可靠性工作阻塞。

---

## 2. 当前代码证据与问题判断

### 2.1 已确认的结构性问题 A：Worker 状态心跳会在长任务中“过期”

当前 Worker 有两套不同概念：

- **任务 LeaseHeartbeat**：处理任务时每隔固定时间续租，避免任务被错误回收。
- **WorkerStateStore 心跳**：只在 Worker `run_once()` 开始执行任务前、任务结束后写一次状态文件。

Worker 状态文件默认 `45 秒` 判 stale。也就是说，只要一个正常任务执行超过 45 秒，哪怕任务 lease 仍在续租、Worker 进程也完全活着，API 读取 worker-status 时仍可能把 Worker 判成：

`offline / worker_heartbeat_stale`

这是一个非常强的“复杂任务越容易看起来断链”的解释，而且与本地模型是否真的崩溃是两件事。

**结论：这是必须修复的确定缺陷。** Worker 执行期间必须有独立状态心跳，不能把“任务完成事件”当作 Worker 心跳。

### 2.2 已确认的结构性问题 B：Windows WebSocket Pong 判定过于激进

当前 Windows 事件流默认：

- 应用层 Ping：约每 1 秒一次
- Pong 超时：约 2 秒
- 失败后自动进入 Reconnecting

Mac Core 的事件发送与 Pong 发送又共享发送锁。忙时、事件重放时、系统瞬时抖动时，Pong 延迟超过 2 秒并不等于 Mac Core 失效。

**结论：单次 2 秒延迟不应把整个 Mac Core UI 判成“正在重连”。**

### 2.3 已确认的结构性风险 C：本地模型调用没有独立故障域

当前本地分析通过 Worker 同步进入 `LocalIntelligenceAdapter.analyze()`，再进入 PydanticAI/Ollama 调用。虽然任务 lease 有后台续租，但：

- 模型生成没有独立 Model Runner 进程；
- 没有每个本地模型 Job 的硬 Deadline；
- 没有独立 Watchdog 可以在 Ollama 请求卡死时结束该 Job 而保住 Worker；
- 没有针对 timeout / connection refused / invalid structured output / OOM suspect 的统一分类；
- 没有 circuit breaker；
- 没有执行中 progress/checkpoint 事件。

所以复杂任务一旦进入长推理，用户会同时遇到：没有进度 + Worker 状态 stale + WebSocket 可能短暂重连，主观上就会非常像“Agent 链断掉了”。

### 2.4 Ollama 常驻策略需要观测后再优化

当前 `ResidentManager` 会在模型未运行时执行 preload，并使用永久 keep-alive 语义。Ollama 官方说明：负数 `keep_alive` 会让模型持续驻留；更大的 context 会消耗更多内存；`/api/ps` 可以查看当前模型、内存/VRAM 占用和上下文信息；Mac 日志默认在 `~/.ollama/logs/server.log`。

这不等于“永久常驻一定错误”，但在统一内存 Mac 上，**必须把实际内存压力、模型 context、加载/卸载、生成耗时一起纳入诊断**，不能仅用“模型在 /api/ps 里”判断健康。

---

## 3. 总体架构：四个故障域必须分离

```text
Windows PicotooPet — Superpower v1.0
        │
        ├── REST Health / Snapshot / Progress  ────────┐
        │                                               │
        └── WebSocket realtime events                  │
                                                        ▼
                                                Mac Core
                                           Source of Truth
                                      Goal / Task / Progress
                                     Result / Health / Audit
                                                        │
                                                        ▼
                                                Mac Worker
                                          Queue / Lease / Checkpoint
                                                        │
                              ┌─────────────────────────┼────────────────────────┐
                              ▼                         ▼                        ▼
                       Research Gateway          Local Model Runner       Coding Providers
                       read-only adapters        isolated process        Codex / Claude
                                                        │
                                                        ▼
                                                     Ollama
                                                 gpt-oss:20b
```

设计原则：

- **Mac Core 必须最难死**：不执行重推理，不被 Ollama 阻塞。
- **Worker 必须保持 heartbeat**：任务再复杂也要持续证明自己活着。
- **Model Runner 是可牺牲进程**：推理超时、死锁或客户端异常只杀这个 Job，不杀 Worker。
- **Ollama 是外部依赖**：可以 degraded，可以重启，可以暂时不可用；Workflow 仍保留 checkpoint。
- **WebSocket 是实时加速通道，不是唯一生命线**：断线时 REST snapshot 继续工作。

---

## 4. Superpower v1.0 可靠性状态模型

每个组件独立显示状态，禁止继续用一个“Mac Core 正在重连”代表所有问题。

| 组件 | 正常状态 | 降级状态示例 | 真故障状态示例 |
|---|---|---|---|
| Mac Core | online | event_stream_degraded | core_unreachable |
| Event Stream | online | reconnecting | auth_failed |
| Mac Worker | idle / executing | lease_warning | worker_process_offline |
| Research Gateway | ready | partial_provider_failure | gateway_unavailable |
| Ollama | ready / generating | slow / circuit_open | server_unreachable |
| Local Model Job | running | retrying / chunk_reduced | timeout / invalid_output |
| Goal Workflow | running | waiting_dependency | failed / cancelled |

Windows 顶部状态建议改为：

```text
Mac Core   在线
Worker     执行中
Research   正常
Ollama     推理中
实时事件   正常 / 重连中
最后同步   2 秒前
```

只有 `Mac Core REST health` 真正不可达时，才把 Mac Core 标成离线。

---

## 5. Worker 双心跳修复

### 5.1 分开两类 heartbeat

**Task Lease Heartbeat**：继续负责任务 lease 续租。  
**Worker Liveness Heartbeat**：新增独立后台 heartbeat，执行任务期间也每 10-15 秒刷新 `worker-status.json`。

执行中状态必须持续包含：

```json
{
  "state": "online",
  "reason": "executing",
  "active_task_id": "...",
  "last_heartbeat_at": "...",
  "active_stage": "local-analysis",
  "last_progress_at": "..."
}
```

### 5.2 stale 判定

- Worker heartbeat 建议 10-15 秒。
- stale threshold 保留约 45-60 秒，但必须由独立 heartbeat 持续刷新。
- 任务正在执行但 heartbeat stale：显示 **Worker process suspected stalled**，而不是把任务直接重跑。
- lease 仍在续租、Worker status stale：诊断系统明确标记 `WORKER_STATUS_HEARTBEAT_STALE_WHILE_LEASE_ALIVE`，这是程序缺陷/状态层异常，不是 Ollama 崩溃。

---

## 6. Windows ↔ Mac 长连接稳定性

### 6.1 双通道

**REST：权威兜底**

- `/health`
- worker status
- goal/workflow/task snapshot
- progress snapshot
- latest component health

**WebSocket：实时增量**

- task progress events
- state changes
- result ready
- component health changes

### 6.2 Pong 机制

不再使用“一次 2 秒 Pong 超时 = 掉线”。

建议：

- Ping 周期降低到 5-10 秒；
- Pong deadline 10-15 秒；
- 任何有效入站业务事件视为连接仍有生命；
- 连续多次无入站 + REST health 同时失败，才判 Core unavailable；
- WS 失败但 REST 正常：状态显示 `实时事件重连中`，任务仍正常运行。

### 6.3 断线恢复

继续使用现有 `after_sequence` 事件续传：

1. Windows 记住最后已消费 event sequence；
2. WS 断开后 REST snapshot 保持 UI 更新；
3. WS 重连后从 `after_sequence` 补事件；
4. 去重后恢复实时模式。

---

## 7. 本地模型隔离：Local Model Runner

### 7.1 为什么必须独立进程

模型调用发生 timeout、PydanticAI 卡住、HTTP socket 异常、JSON 解析卡住时，Worker 主循环必须仍然可心跳、可取消、可保存 checkpoint。

因此新增短生命周期隔离执行器：

```text
Worker
  │
  ├── 写入 bounded job input（临时文件 / pipe）
  ├── 启动 picotoopet-model-runner 子进程
  ├── Watchdog 监视 deadline / cancel / process exit
  ├── 持续更新 progress
  └── 读取 validated result
```

Ollama 模型本身仍由 Ollama Server 托管，因此每个 Job 新建 Python 子进程不会重复加载 20B 模型。

### 7.2 Model Job 状态

```text
queued
starting
ollama_probe
running
validating
completed
retry_wait
circuit_open
failed
cancelled
```

### 7.3 Deadline

每个角色配置明确 deadline，而不是无限等：

- scout/filter：短 deadline
- analyst/judge：中等 deadline
- editor：短 deadline

具体秒数由真实 Mac benchmark 决定，不在代码里凭感觉写死；CI 使用虚拟时钟/fixture 验证边界。

### 7.4 失败不会直接重跑整个 Workflow

模型 Job 失败后：

```text
保存 checkpoint
→ 分类原因
→ 必要时缩小输入
→ 有界重试
→ 仍失败则 circuit open
→ 后台健康 probe
→ 恢复后从当前 stage 继续
```

网络搜索、已取得 Evidence、前面完成的 Workflow step 不重复消耗。

---

## 8. gpt-oss:20b 负载控制

### 8.1 不盲目把上下文调大

Ollama 官方说明 context 增大显著增加内存需求。我们的任务与“通用聊天 Agent”不同，可以通过分块和分层综合避免一次塞入超大上下文。

策略：

```text
Evidence
→ deterministic dedupe
→ bounded chunks
→ FILTER / SCOUT 小块处理
→ compact intermediate summaries
→ ANALYST 综合
→ JUDGE 检查证据充分性
→ EDITOR 输出
```

### 8.2 自适应预算

运行前采集：

- `ollama /api/ps`
- 模型 context
- model size / size_vram（API 有则记录多少）
- macOS 总内存
- memory pressure
- 当前是否还有其它 Ollama model loaded
- 输入估算 token 数

按 headroom 选择：

- chunk size
- concurrency（本地模型默认 1）
- num_ctx
- retry 时缩小比例

不自动停止用户其它模型；只允许管理 PicotooPet 自己的 gpt-oss:20b Job。

### 8.3 Resident 策略

不再只用“永久驻留成功”作为健康指标。

健康指标包括：

- server reachable
- model installed
- model loaded
- context
- memory headroom
- last generation latency
- recent timeout count
- recent structured-output failure count

keep-alive 是否永久由内存诊断决定；默认先保持现有行为兼容，在收集足够真实 Mac 证据前不贸然改变。

---

## 9. 原因定位：Superpower Black Box Diagnostics

这是本轮最关键的新增之一。每次异常都先**留证据，再自愈**，避免像 OpenClaw 一样只看到“断了”却不知道为什么。

### 9.1 一次故障快照记录什么

**PicotooPet 状态**

- goal/workflow/task ID
- 当前 stage
- 当前 progress counters
- task lease last renewed
- worker-status last heartbeat
- Core health
- event stream state

**Ollama 状态**

- `/api/version`
- `/api/ps`
- gpt-oss:20b installed/running
- current context / memory fields（API 提供多少记录多少）
- 当前 Job elapsed
- 输入字符数、估算 tokens（不默认记录完整 Prompt）
- recent timeout / error class

**Mac 系统状态**

- memory pressure
- free/available disk
- Ollama PID 是否存在
- Worker PID 是否存在
- Core PID 是否存在

**日志**

- PicotooPet Core/Worker 最近 bounded tail
- `~/.ollama/logs/server.log` 最近 bounded tail
- launchd 相关最近 bounded events

默认不采集：Cookie、Token、浏览器存储、完整研究正文、完整 Prompt、密码、API key。

### 9.2 故障分类码

至少包括：

```text
WS_PONG_TIMEOUT_FALSE_POSITIVE
REST_CORE_UNREACHABLE
WORKER_STATUS_HEARTBEAT_STALE
WORKER_LEASE_LOST
MODEL_RUNNER_TIMEOUT
OLLAMA_CONNECTION_REFUSED
OLLAMA_HTTP_ERROR
OLLAMA_MODEL_NOT_LOADED
OLLAMA_CONTEXT_PRESSURE
OLLAMA_MEMORY_PRESSURE_SUSPECTED
LOCAL_MODEL_INVALID_STRUCTURED_OUTPUT
LOCAL_MODEL_REPEATED_TIMEOUT
RESEARCH_GATEWAY_TIMEOUT
PROGRESS_STALLED_BUT_WORKER_ALIVE
```

### 9.3 一键诊断包

Windows “诊断”页面增加：

`生成最近一次故障诊断包`

Mac Core 生成脱敏 ZIP，包含：

- `summary.json`
- `component_health.json`
- `task_progress.json`
- `ollama_snapshot.json`
- `ollama_server_tail.log`
- `worker_tail.log`
- `core_tail.log`
- `README_CN.txt`

这样用户下次说“又断了”，不再需要靠截图猜原因。

---

## 10. Circuit Breaker 与自动恢复

### 10.1 Ollama circuit breaker

示例逻辑：

- 单次 timeout：记录，缩小输入，有界 retry。
- 连续 2 次同类 timeout：打开 circuit，停止立即重试。
- circuit open：每 30-60 秒做轻量 probe。
- probe 恢复：从 checkpoint 恢复 stage。
- 长时间不恢复：Goal 显示“等待本地模型”，而不是“处理中”。

### 10.2 自动重启边界

只有在明确确认：

- Ollama server 不可达；
- 当前没有活跃 Model Job；
- 已经先完成诊断快照；

才允许一次受控的 Ollama 恢复动作，并限制频率。

禁止：

- 无限 restart loop；
- 因为一次 timeout 就重启 Ollama；
- 自动杀其它用户模型；
- 删除模型或重新下载模型。

---

## 11. 真实进度协议

进度必须是 Durable Fact，而不是 UI 动画。

新增统一 `TaskProgressSnapshot` / `TaskProgressEvent`，字段至少：

```text
task_id
goal_id
workflow_id
stage_key
stage_label
state
completed_units
total_units
unit_label
last_activity_at
message
attempt
checkpoint_version
component
```

### 11.1 Discovery

显示真实单位：

- 查询计划：0/N
- 当前 query
- 成功搜索：N
- 失败搜索：N
- Evidence：N
- Candidate：N
- Cluster：N
- Scout：queued/running/completed

### 11.2 Synthesis

- evidence chunks：0/N
- filter chunks：0/N
- analyst：running/completed
- judge：running/completed（需要时）
- confidence available

### 11.3 Handoff

- build context
- render manifest
- package zip
- hash
- ready

### 11.4 不使用假的百分比

UI 优先显示：

`3 / 6 查询`、`2 / 4 分块`、`18 条证据`

如果需要总体百分比，只显示“预计总体进度”，并由固定 stage weights 计算，不能伪装成模型真实 token 进度。

---

## 12. Windows 任务详情页面

### 12.1 运行中

右侧不再显示“当前没有可显示结果”，改成：

```text
当前阶段：本地分析
阶段进度：2 / 4 分块
最后活动：3 秒前
运行时间：01:38
Worker：在线 / executing
Ollama：generating

最近活动
22:51:04  搜索 2/6 完成
22:51:08  新增 8 条证据
22:51:17  搜索 3/6 完成
22:51:20  开始本地 Scout
```

### 12.2 Stalled 判定

如果 progress 很久不变：

- Worker heartbeat 正常 + Model Job running：显示“模型仍在推理，暂无新输出”。
- Worker heartbeat 正常 + Ollama probe failed：显示“本地模型异常，已保存进度并恢复中”。
- Worker heartbeat stale：显示“Worker 心跳异常，正在诊断”。
- Core REST 不可达：显示“Mac Core 无法连接”。

这样用户能知道**是慢、是卡、是模型坏，还是网络真断**。

### 12.3 完成后

显示：

- executive summary
- confidence
- findings
- recommended actions
- evidence count / sources
- research stop reason
- Handoff 下载（如果该 Goal 需要）

底层 `autonomous.discovery.v1` 等类型默认隐藏到“高级诊断信息”。

---

## 13. 产品版本与命名

### 13.1 用户可见

```text
产品名：PicotooPet AI
公开版本：Superpower v1.0
窗口标题：PicotooPet AI — Superpower v1.0
```

### 13.2 工程内部

```text
Engineering build: 2.3.27.1.<ci-build>
Commit: <sha>
Runtime: 2.3.0-slice-d-worker-<build>-<sha>
```

普通用户页面不再把 `2.3.26.1` 当产品版本展示。

### 13.3 兼容策略

如果现有安装/升级合同仍依赖 `2.3.x` SemVer，则：

- 保留工程 version 字段；
- 新增 public product identity；
- Windows title/about 使用 public identity；
- diagnostics/about advanced 显示两者；
- 不通过简单删除工程版本破坏升级链。

---

## 14. 全自动 Goal Orchestrator 的产品形态

用户只看到高层 Goal：

```text
研究产品
找消费者痛点
寻找商业机会
生成 AI 视频方案
从产品研究到视频
```

内部固定：

```text
Goal
→ Discovery
→ Synthesis
→ Handoff（适用时）
```

用户不需要手工启动第二步、第三步。

Web GPT 暂时：

```text
自动生成 Handoff ZIP + 固定 Prompt
→ Windows 明确提示“交接包已就绪”
→ 用户人工上传网页 ChatGPT
```

不自动读取/写入 ChatGPT 登录态。

---

## 15. 验证矩阵

必须先 RED，再 GREEN。不能只测“接口返回 200”。

### A. Worker 心跳

1. handler 模拟运行 120 秒；Worker status 全程不得 stale。
2. lease heartbeat 与 liveness heartbeat 分别失败时能区分原因。
3. Worker 真被 kill 后，超过阈值才正确 offline。

### B. Windows ↔ Mac

4. WS 人为断开 30 秒，REST 仍更新进度。
5. WS 恢复后按 sequence 补事件，不重复。
6. Pong 延迟 5 秒时不得把 Mac Core 判 offline。
7. Core REST 真断开时正确 offline。

### C. Ollama / Model Runner

8. Ollama connection refused。
9. HTTP 500。
10. 请求超过 deadline。
11. 子进程卡死可被 watchdog 结束，Worker 仍 heartbeat。
12. structured output 无效。
13. context/input 过大时自动分块而不是硬顶。
14. repeated timeout 打开 circuit。
15. circuit probe 恢复后从 checkpoint 继续。
16. Ollama server crash 时生成诊断包。

### D. Progress

17. Discovery 6 queries 逐条增加进度。
18. Synthesis 4 chunks 逐块增加进度。
19. Windows 重启后恢复当前 progress snapshot。
20. WS 断线期间 progress 由 REST 继续更新。
21. 最终结果替换运行面板，不丢历史活动。

### E. 产品版本

22. 标题栏、首页、About 都显示 Superpower v1.0。
23. Advanced diagnostics 显示 engineering build。
24. 安装/升级/回滚仍兼容现有 2.3.x lineage。

### F. 长时间 soak

25. 连续运行 2 小时混合 Research + Local Analysis。
26. 多次 Ollama load/generate，无 Worker stale。
27. 网络短抖动多次，不产生假 Core offline。
28. 复杂任务完成后无 orphan runner process。

---

## 16. 分阶段实施

### Phase R0 — Diagnostics First

先做最小诊断增强，不改变行为：

- Worker liveness / lease 观测；
- Ollama `/api/ps` + version + log tail；
- Windows WS disconnect reason；
- 一键故障快照。

目的：在修复之前就能捕获真实 Mac 证据。

### Phase R1 — False Disconnect Fix

- Worker 独立 liveness heartbeat；
- WS / REST 双通道；
- 宽容的 WS liveness；
- component health 拆分。

### Phase R2 — Durable Progress

- progress repository/event contract；
- Discovery/Synthesis/Handoff 发 progress；
- Windows 运行监控 UI。

### Phase R3 — Local Model Isolation

- isolated model runner；
- deadline/watchdog；
- error taxonomy；
- checkpoint/retry/circuit breaker；
- adaptive chunking。

### Phase R4 — Superpower v1.0 Product Identity

- public version identity；
- Windows title/about；
- build/manifest/install reports dual-version；
- UI 隐藏内部 task type。

### Phase R5 — Native CI + Real Mac Acceptance

- Mac Core CI
- Mac Worker arm64 CI
- Windows WPF CI
- install/upgrade/recovery/rollback
- real Mac soak + fault injection
- Windows UI Preview / acceptance installer

---

## 17. 交付物

最终至少交付：

1. Superpower v1.0 设计规范。
2. 实现计划与 RED test 清单。
3. Mac Core 更新包。
4. Mac Worker 更新包。
5. Windows x64 Preview/Acceptance 安装包。
6. 一键诊断命令/诊断包入口。
7. Superpower v1.0 产品身份更新。
8. CI run 证据。
9. 实机故障注入与 soak 结果。
10. Rollback。

---

## 18. 验收定义

以下全部满足，才允许说“Superpower v1.0 可靠性完成”：

- 一个正常运行 2 分钟以上的本地模型任务不会让 Worker 被误判 offline。
- Ollama generation 卡住时，Worker/Core/Windows 控制面仍在线。
- Ollama 崩溃后能明确告诉用户原因类别，并生成诊断证据。
- Workflow 在 Ollama 恢复后从当前 checkpoint 继续，而不是从头重跑研究。
- Windows 在运行中持续显示可验证进度和最后活动。
- WebSocket 短暂断线时 REST 继续更新，恢复后事件续传无重复。
- UI 不再暴露 `autonomous.discovery.v1` 作为普通用户主标题。
- 产品公开身份统一为 `PicotooPet AI — Superpower v1.0`。
- 现有安全边界不被放宽。

---

## 19. 最终设计结论

Superpower v1.0 的可靠性目标不是“保证 gpt-oss:20b 永不出错”。任何本地模型、网络服务和进程都可能出错。

真正的目标是：

> **即使 Ollama 出错，也必须能够知道为什么；即使模型卡住，也不能拖死 Worker；即使 Worker 在长任务中很忙，也不能被误判离线；即使 WebSocket 抖动，Windows 也要继续看到真实进度；任何一步失败都保留 checkpoint，可恢复、可审计、可诊断。**

这套设计把“模型性能问题”“Worker 心跳问题”“Mac 通讯问题”“Workflow 失败”拆成独立故障域，因此能真正解决之前复杂任务一上来就像整条 Agent 链断掉的问题，而不是继续堆 timeout。
