# Phase 2 性能优先纵向切片设计

## 目标

在不削减冻结功能、安全边界、审计和恢复能力的前提下，完成首条可独立验收的双机控制链：

```text
Windows Desktop 提交任务
→ Mac Core 在 SQLite 中耐久入队
→ 事务型 Outbox 产生顺序事件
→ WebSocket 低延迟推送
→ Windows Desktop 增量更新状态
```

本切片是 Phase 2 的第一块可运行产品，不包含 ComfyUI Worker、Maotai Connector、知识库或 Grok Build 执行。

## 技术基线

- Windows Desktop 使用 .NET 10 LTS、WPF、MVVM 和 C# 14。
- Mac Core 保持 Python 3.12/3.13、FastAPI、SQLite WAL、PydanticAI 和现有冻结组件。
- 控制面使用 REST；实时事件使用 WebSocket；大型文件不进入 WebSocket。
- 所有业务写入先提交 SQLite，再对外确认；不以降低耐久性换延迟。
- 所有代码包含对齐的中文注释，日志不得记录明文 Token。

## 体系结构

### Mac Core

1. `TraceMiddleware`
   - 接收或生成 `X-Picotoo-Trace-Id`。
   - 在响应中返回 Trace ID 与 `Server-Timing`。
   - 记录请求耗时，不记录认证秘密。

2. `QueueRepository + EventOutbox`
   - 任务创建和状态转换在同一 SQLite 事务内写入 `task_events` 与 `event_outbox`。
   - Outbox 的 SQLite `rowid` 作为严格递增 `sequence`。
   - 幂等请求返回既有任务，但不重复产生业务副作用。

3. `OutboxDispatcher`
   - 应用生命周期内后台运行。
   - 批量领取未投递事件，发布到内存 Broker 后确认。
   - 崩溃后重新领取未确认事件。

4. `EventBroker`
   - 每订阅者使用有界队列。
   - 关键事件采用背压，不允许静默丢弃。
   - 可合并进度事件后续由 Worker 阶段加入，本切片不丢事件。

5. `WebSocket /events`
   - 支持 `after_sequence`。
   - 连接后先补发持久 Outbox 中的缺失事件，再进入实时流。
   - 每个事件包含 `sequence`、`event_id`、`topic`、`trace_id`、`created_at` 与 `payload`。
   - 支持应用级 `ping/pong`，用于桌面端测量链路延迟。

### Windows Desktop

1. `PicotooPet.Desktop.Core`
   - 不依赖 WPF，负责 REST、WebSocket、重连、状态归并和延迟统计。
   - 使用长生命周期 `HttpClient` 与连接池。
   - 使用 `ClientWebSocket`、指数退避、随机抖动和事件续传。
   - 事件接收进入有界 `Channel<T>`，再由单读者顺序归并。

2. `PicotooPet.Desktop`
   - WPF + MVVM。
   - 首条纵向切片提供连接状态、Mac 健康、快速创建任务、任务列表和链路延迟。
   - UI 线程不执行网络或磁盘 I/O。
   - ListView 启用虚拟化和容器复用。

3. `CredentialManagerTokenStore`
   - Token 存入 Windows Credential Manager。
   - 日志、配置 JSON 和异常中不得出现 Token。

4. `LatencyRecorder`
   - 记录 REST 和 WebSocket 样本。
   - 输出 count、p50、p95、p99、max。
   - 使用单调时钟测量本机耗时。

## 性能 SLO

在有线千兆局域网、Mac 与 Windows 空闲、连续 500 次请求条件下：

- `GET /health`：p95 ≤ 50 ms，p99 ≤ 100 ms。
- `POST /tasks`：p95 ≤ 80 ms，p99 ≤ 150 ms。
- 任务创建到 Windows 收到对应事件：p95 ≤ 150 ms，p99 ≤ 300 ms。
- WebSocket 应用级 ping 往返：p95 ≤ 50 ms，p99 ≤ 120 ms。
- Windows 点击后视觉反馈：p95 ≤ 100 ms。
- 断网识别 ≤ 2 秒；网络恢复后 p95 ≤ 5 秒重新在线。

测试报告必须包含分位数，不能只报告平均值。

## 一致性与恢复

- REST 采用 `Idempotency-Key`，桌面端重试复用同一键。
- WebSocket 事件使用单调 `sequence`，重连从最后确认序号续传。
- 重复事件按 `event_id` 去重，旧序号不回滚界面状态。
- Outbox 至少一次投递；客户端幂等消费，实现业务效果只生效一次。
- SQLite、Outbox 和任务状态在同一事务边界内提交。
- 断线期间不丢任务，恢复时只补发缺失事件。

## 错误处理

每个用户可见错误包含：

- 中文摘要
- 机器错误码
- `trace_id`
- 是否可重试
- 建议操作
- 日志位置

认证失败、超时、断网和服务重启必须表现为不同状态，不显示“未知错误”。

## 测试边界

### 本环境可完成

- Mac Core 单元、集成、契约、幂等、Outbox、WebSocket 续传和性能微基准。
- Windows Core 源码、无第三方依赖测试控制台、静态契约检查。
- WPF 项目结构、XAML、MVVM 与安装/验证脚本生成。

### 必须在 Windows 实机完成

- WPF 编译、发布与真实启动时间。
- Credential Manager 实写。
- Windows 与 Mac 的真实局域网 p50/p95/p99。
- 休眠、唤醒、拔网线和系统通知。

## 验收门

本切片只有在以下条件均成立时进入 Phase 2 后续页面扩展：

- Mac 全套 Python 测试通过。
- Outbox 事务一致性与 WebSocket 断线续传测试通过。
- Windows Core 无第三方包测试项目可在 .NET 10 编译运行。
- WPF 应用可在 Windows 11 启动且不弹终端。
- 真实双机 SLO 报告通过；任一 p95/p99 超标必须定位后再扩展功能。
