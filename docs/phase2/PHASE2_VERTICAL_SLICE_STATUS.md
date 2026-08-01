# Picotoo Pet V2 — Phase 2 性能纵向切片状态

## 当前结论

本阶段已完成第一条双机控制链的源码实现与本地自动化验证：

```text
Windows Desktop 创建任务
→ Mac REST API 接收并写入 SQLite
→ Task Event 与 Outbox 在同一事务提交
→ WebSocket 按 sequence 推送或重放
→ Windows 状态仓库幂等归并
→ WPF 任务列表增量更新
```

该切片不依赖 Wan、ComfyUI 或 Windows GPU 模型，可与视觉模型安装问题独立推进。

## 已实现

### Mac Core

- Trace ID 贯穿 REST 请求、错误和任务事件。
- `Server-Timing` 返回服务端处理耗时。
- Task、Task Event、Outbox 在同一 SQLite 事务中提交。
- Outbox 事件具有单调递增 `sequence`，支持断线重放。
- WebSocket 使用有界订阅队列、应用级 Ping/Pong 和 `after_sequence` 续传。
- Phase 2 升级保留既有 macOS Keychain API Token，不破坏已配对设备。
- 包版本统一为 `2.2.0-phase2-slice1`。

### Windows Desktop

- .NET 10、C# 14、WPF、MVVM。
- 长生命周期 `HttpClient`、连接池、幂等键、Trace Header。
- `ClientWebSocket`、指数退避、随机抖动、事件序号续传。
- 两秒 Pong 超时检测半连接，自动进入重连。
- 有界 `Channel<T>`、单读者顺序归并和重复事件去重。
- Windows Credential Manager 保存设备 Token。
- WPF 列表虚拟化、容器复用和增量任务更新。
- 安装、验证、回滚均提供隐藏终端的 VBS 双击入口。
- 安装器采用版本目录、SHA-256 清单、原子版本指针和并发安装锁。
- 诊断器测量 REST、WebSocket、任务提交和任务事件回传延迟，并输出 p50/p95/p99。

## 仍需 Windows 与双机实机验收

当前执行环境不是 Windows 11，也没有 .NET Windows Desktop 编译工具链，因此以下项目不能在本环境宣称完成：

- WPF 在 Windows 11 上的实际编译、发布和启动。
- Windows Credential Manager 的真实写入与读取。
- Windows 与 Mac 局域网真实 p50/p95/p99。
- 拔网线、Wi-Fi 切换、休眠、唤醒和系统重启恢复。
- 冷启动、热启动、UI 帧率、长期内存和句柄稳定性。

只有 `REAL_MACHINE_ACCEPTANCE_CN.md` 中的实机门槛全部通过，Phase 2 纵向切片才可标记为实机验收完成。

## 不在本切片范围

- ComfyUI、Wan、VACE 实际任务执行。
- faster-whisper、FFmpeg、RIFE、Real-ESRGAN、SAM2 Worker。
- Maotai、视频助手和创作助手 Connector。
- Grok Build/Codex 工程执行层。
- BGE-M3、Qdrant、夜间批处理和最终全局面板的全部页面。

这些功能未被删除，仍按冻结路线在后续切片实现。

## 本地发布验证证据

在当前 Linux 构建容器中，Mac Core 以真实 Uvicorn 进程运行，并完成 500 样本回环基准：

| 指标 | p50 | p95 | p99 | 最大值 |
|---|---:|---:|---:|---:|
| Health REST | 0.772 ms | 1.060 ms | 1.813 ms | 50.838 ms |
| Task Submit | 3.079 ms | 5.193 ms | 10.840 ms | 500.894 ms |
| Task → WebSocket Event | 21.661 ms | 24.170 ms | 30.402 ms | 519.323 ms |
| WebSocket Ping/Pong | 0.128 ms | 0.195 ms | 0.386 ms | 0.550 ms |

这些数字只证明本机代码路径和真实 HTTP/WebSocket 服务满足低延迟设计，不代表两台实体电脑之间的局域网验收。Windows WPF 编译、Credential Manager、实际有线网络和断线恢复仍必须按实机报告判定。

当前自动测试：`132 passed`。发布结构、秘密扫描、PowerShell UTF-8 BOM、Python 字节码、Bash 语法、XAML/XML 和 JSON 解析均单独验证。
