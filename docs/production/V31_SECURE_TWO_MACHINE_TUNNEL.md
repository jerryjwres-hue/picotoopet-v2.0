# PicotooPet V3.1｜Mac ↔ Windows 安全连接（本机 OpenSSH，无新服务）

## 结果和边界

此前 Windows 安装版 Studio 默认使用 `http://192.168.1.161:8766`，带设备
Bearer 的局域网明文 HTTP 不符合 #289 Worker 的 HTTPS/loopback 门禁。
现有 Mac Core 默认启动的也是 HTTP；仅增加 Worker HMAC 无法使两台机器通信。

本轮只引入**系统自带 SSH 本地端口转发**。Windows 上
`CONNECT_MAC_SECURE.vbs` 启动 `Start-SecureMacTunnel.ps1`，它用
Windows 系统的 `ssh.exe`（不下载依赖）建立：

```text
Windows Studio / Worker / FrameTransfer
     http://127.0.0.1:18766
             │ 仅 Windows 本机
             │ SSH（系统公钥认证 + 已信任的 known_hosts）
             ▼
Mac SSH Remote Login → Mac 127.0.0.1:8766 （或实际 Core 端口）
```

Mac Core 原有 REST、SQLite、Owner/Master、Worker Journal 和 GPU HOLD 不变。
不暴露公网，不修改 Windows HTTP 验证回调，不放宽 HTTPS、不传输 Owner Token。
SSH 仅承载原有受设备 Bearer 认证的 API，**不等于 Owner 或 GPU 授权**。
手机 HTTPS 网页是另一条路径，本轮未设置手机远程访问。

## 用户首次操作（一次性安全前提）

1. Mac：在 **系统设置 → 通用 → 共享 → 远程登录**中只允许必要的 Mac 用户，
   并为 Windows 用户的 SSH 公钥设置授权。Mac 本地 `VERIFY_MAC.command`
   会显示现有 Mac Core 端口（可能是 8765/8766）。
2. Windows：须已启用系统 OpenSSH Client，并事先使用受信任的
   SSH host key 记录（`known_hosts`）和 SSH 公钥登录；不要关闭严格
   host key 检查，不要把 Mac 账户密码/私钥粘贴到 Studio。
3. 在解压的受信任 Windows 安装包中**双击 `CONNECT_MAC_SECURE.vbs`**。
   首次填 Mac IP/主机名、Mac 用户名和现有 Core 端口；以后复用
   `%LOCALAPPDATA%\\PicotooPetV2\\DesktopApp\\secure-mac-tunnel.json`
   的无敏感配置。脚本只在 SSH 隧道创建成功并从本机端口取得
   `/api/v1/health` 后输出 `SECURE_MAC_TUNNEL=READY`。
4. 打开 Windows Studio → 连接设置：Mac Core 地址使用
   `http://127.0.0.1:18766`，设备令牌沿用原来 Windows Credential Manager
   的配对；视频项目和 Worker 独立密钥沿用 PR #291 一次配置。
   此后所有已有 Windows Core API/Worker 请求复用此本机地址。

**安装后持续使用：** 新版 Windows 预编译安装器还会把 `CONNECT_MAC_SECURE.vbs` 和 `Start-SecureMacTunnel.ps1` 复制到当前版本的 `tools/connection`，并加入 SHA256 发布清单；开始菜单提供“Picotoo Pet 安全连接”快捷方式，避免丢失 ZIP 后不能重新连 Mac。回滚到旧版本时快捷方式同步切换或清理。`VERIFY_PHASE2_WINDOWS.vbs` 使用 `http://127.0.0.1:18766`，拒绝旧明文 LAN HTTP。

SSH 认证失败、主机密钥陌生/变更、端口占用、Core 不可达时**明确 FAIL**，
不会假装连接成功、不自动信任新 host key、不回退到明文局域网 HTTP。
只有 Mac 系统用户事先允许的 SSH 公钥可建立连接。SSH 进程在 Windows 登录会话中持续运行；
重启 Windows、断网或 SSH 会话终止后，需要重新启动入口。
**尚未实现自动自愈/开机拉起，不要声称 Windows 无人值守已验收。**

## 测试和非目标

- `Start-SecureMacTunnel.ps1 -SelfTest`：Windows PowerShell 5.1 上只验证
  SSH 命令安全选项、地址/用户名限制，**不启动 SSH、不连接 Mac**。
- 原生 Windows 发布构建要求该测试 PASS 才允许生成 ZIP，ZIP 包含双击入口。
- WPF 生产页 smoke：确认 Studio 默认 URL 是本机环回，Worker 同样接受；
  Studio 对旧局域网 HTTP 提示“请先开启安全隧道”，拒绝把设备 Bearer 发出去。
- 原有 macOS/Windows CPU CI 不能代替两个实际设备上的 SSH 握手、
  用户公钥授权、Worker 认证和后续真实视频生产验收。
- 此改动不增加另一套 Worker、任务队列、后台导演、云服务或 GPU 调用；
  不下载/安装模型，不改变任何生产审批逻辑。

如果现有 Mac 已通过独立、可信 HTTPS 代理部署 Core，则直接在 Studio
使用原 HTTPS 地址即可，**不需要同时启用 SSH 隧道**。
