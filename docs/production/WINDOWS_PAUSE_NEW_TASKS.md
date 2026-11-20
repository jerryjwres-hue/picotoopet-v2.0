# PicotooPet｜Windows 只暂停新任务（轻量操作开关）

这不是第二套调度器，也不是 GPU HOLD / OwnerPrincipal 的替代品。

## 原有架构中的位置

Windows `scripts/windows/executor_bridge.py` 已负责 Mac Core 租约、Journal 重启恢复、
本地 `_queue` 输入和回执。增加一个 **Windows 本地文件开关**，控制当前 worker_id
是否继续向 Mac Core 领取新租约。Mac Core、数据库、任务状态机、ComfyUI
和已有的 Worker 不需修改。

开关文件位于现有项目目录内：

    _queue/executor_bridge/<worker_id>.pause-new.json

本机操作者只需在执行桥已有 TOML 的目录运行：

```powershell
# 暂停当前 Windows bridge 领取新任务；不访问 Mac Core，不关闭 GPU。
python scripts/windows/executor_bridge.py scripts/windows/executor_bridge.toml --pause-new

# 只读检查状态；不读取、不打印设备 Token。
python scripts/windows/executor_bridge.py scripts/windows/executor_bridge.toml --pause-status

# 恢复领取新任务；仍需原有 Core/Worker 安全许可。
python scripts/windows/executor_bridge.py scripts/windows/executor_bridge.toml --resume-new
```

这些操作不需要 `PICOTOO_EXECUTOR_TOKEN`，不会启动独立的 Worker 进程、
不访问 Mac Core、不会提交任何 ComfyUI POST。普通运行时不需要增加步骤。

## 行为边界

- 暂停标记存在时：未在执行中的 Bridge 不再发起**新** `/executors/lease`。
- 已领取租约但本地任务尚未提交时：保留原 Journal，继续心跳，不把新文件
  放进 `_queue/inbox`；标记解除后从同一 Journal 继续。
- 已提交到 `_queue/inbox` 或正在 `running` 的任务：原 Worker 可以继续执行；
  已经完成的回执正常向 Mac Core 汇报，不重复领取新任务。
- 崩溃后：暂停文件仍在；先恢复旧 Journal，不重置、清除或覆盖已提交任务。
- 该开关只影响当前 Windows bridge 的 **新任务调度**，不是立刻中止 GPU
  的强制急停，也不暂停其他 Windows Worker、ComfyUI 手动提交或 Mac Core
  上其他同类 Task。
- 本地文件和租约请求之间存在并发边界：若操作者恰在已经通过暂停检查
  后发出新租约的瞬间暂停，可能仍持有一个未提交的租约。Bridge 在实际
  写入新 inbox 文件前再复查暂停标记以降低风险；不要把它描述成
  已认证的全局「零新增 GPU POST」安全保证。
- `--resume-new` 只移除本地暂停标记；绝不改变 GPU HOLD、Owner 授权、
  未通过 QC 的素材状态、或解除 Mac Core 的生产禁令。

## 与候选抽卡预算的关系

已合并的 Episode 预算门禁 #266 控制单份新 Episode 的预估最大请求量。
本操作开关补充“运行到某一阶段先停止领取下一条任务”的人工入口；
**两者都不能替代真实 GPU active time、电力、显存和磁盘的运行时采样**。

仍需后续工作：由正式 Worker 输出具证据的 GPU active time、磁盘消耗；
根据用户指定的累计阈值在 Core 执行层控制租约，保留旧 Journal 和受信任授权；
在获得正式 Owner 操作权限后才开放手机端暂停、追加候选或重绘按钮。

## 离线测试范围

`tests/unit/test_bridge_pause_new.py` 在 Mac Python CI 通过本地假 Session 检查：
暂停后不领取、恢复后只领取一次、已有未提交 Journal 继续心跳、
已提交失败回执不丢失、重启保持暂停、符号链接保护、CLI 无 Token 操作。
这不是实机 Windows/CUDA/ComfyUI 验收。部署前仍需单机只读核对进程、
Journal 和 `_queue`，不应为了验证开关而启动真实 GPU 作业。
