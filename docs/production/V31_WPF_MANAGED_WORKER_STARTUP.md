# PicotooPet V3.1｜Studio 管理现有 Windows Worker（默认不启动）

这一改动不是新执行器。Studio 只启动、暂停已有 `PicotooPet.Worker.exe`；任务读取、旧 Journal、文件 SHA、ComfyUI inbox、QC/剪辑均继续复用旧 Bridge。

## 用户日常操作

首次：连接 Mac Core、选择已有 Windows 视频项目目录，然后点击「一次配对并启动 Worker」。填 Worker ID 和独立配对密钥，勾选「以后打开 Studio 自动启动」。

以后：正常打开 Studio；仅在此前自愿勾选且配置完整时，Studio 自动启动同一个 Worker。连接暂时离线时，Bridge 用已有重试逻辑恢复。Core Owner/Master/冻结 Plan 仍逐条授权；Windows Worker 并不会因为自动启动就能领取 GPU。

需要暂停：点击「暂停新任务」，它只使用原有 Bridge `--pause-new` 标记，**不会终止进行中的 GPU 作业或删除 Journal**。点击「恢复新任务」只取消本地暂停，不解除 Core 的全局 HOLD。

## 安全与一次性配置前提

- Mac Core 必须有可信 HTTPS（同一台机器的 `127.0.0.1` HTTP 除外）。旧默认局域网 HTTP 不允许用于独立 Worker 的自动启动；无需为了省事降低 TLS 验证。
- Windows Studio 的原有 Mac device Bearer 继续存在 Windows Credential Manager；独立 Worker HMAC 则保存在另一 Credential Target `PicotooPetV3/WorkerAttestationKey`，不是普通 JSON 设置、TOML、日志或命令行参数。
- Mac Core 必须另行配置相同 Worker ID 和同一个随机密钥，以及 Owner 审核和独立 MASTER 审核机制。Studio 不会自行修改 Mac 配置、不能伪造 Owner 权限。
- 已配置 HMAC 的 Python Worker，如果 Core challenge 是 204 或密钥不合法，**不再调用 unsigned legacy lease**。默认情况下 GPU 始终 HOLD。
- 非敏感的 Worker ID、项目路径、是否自动启动仍写在原有 DesktopSettingsStore；操作员未勾选之前，自动启动为 false。
- 同一项目、同一 worker_id 的 `.lock` 由原有 Python Bridge 独占；再次打开 Studio 不重复启动第二个 Bridge。
- Studio 退出时不杀死可能在处理旧 Journal 的 Worker；暂停与恢复使用同一个原有 Worker 的本地命令，不清空原始回执。

## 当前验证边界

CI 只覆盖 Windows WPF 真实控件、进程启动前安全拒绝、字节锁、macOS/Python 合成负例以及打包组件。**尚未验证实际 Mac HTTPS 部署、一次性真实密钥配对、Windows 后台长时间运行、ComfyUI、GPU 或三镜头视频质量。**

发布与首次 GPU 授权仍要求人工验收。安装包尚未公开正式代码签名，不得通过陌生来源分发。