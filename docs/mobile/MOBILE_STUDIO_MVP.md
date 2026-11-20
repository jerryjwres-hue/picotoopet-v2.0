# PicotooPet V3.1 — 手机版 Studio MVP（只读）

状态：GitHub 候选代码。**尚未在 Mac mini / Windows / iPhone 上部署测试**。

## 用户入口

手机使用 HTTPS 地址的 `/mobile`。网页无需安装 App 或输入设备 Bearer Token。
已配对 Windows Control Center 的「连接设置」页有 **生成手机配对码** 按钮。
5 分钟内在手机输入一次性配对码，完成后浏览器保存 HttpOnly / Secure /
SameSite=Strict 的短期 Cookie；Mac Core 重启或 8 小时后需重新配对。
手机页面提供任务数量/最新任务、剧集清单、StoryPack JSON 只读预览。
第二阶段可点击剧集进入只读候选画廊，查看 QC 状态、已有 JPEG 缩略图、
选用标记和是否满足合成条件。缩略图只通过有效手机会话从现有 Core
获取，不提供任意文件访问或执行器设备 Token。

**本版不包含**：正式提交故事、触发 GPU、批量抽卡、修改选片决策、审批 OwnerPrincipal、
取消/重试、发布及下载媒体。不要因为界面可登录就声称这些已实现。

## 安全配置

1. 手机接口 **默认关闭**。只有在已部署私有 HTTPS 访问（例如由管理员配置的
   Cloudflare Tunnel + Access 或符合商业许可的私有 VPN/HTTPS 反向代理）并
   验证 Origin、Host、代理头来源之后，才为 Mac Core 设置
   `PICOTOO_MOBILE_STUDIO_ENABLED=1` 并重启服务。
2. 本版本拒绝直接经 HTTP LAN 地址登录。不要把 Mac Core :8765/:8766、
   ComfyUI :8188 或其他设备 REST API 直接映射到互联网。
   **远程隧道必须只转发 /mobile 与 /mobile/* 网页路径**，其余路径默认拒绝，
   尤其是 `/api/v1/*`。一次性配对码在 Windows 通过现有内网设备 API 获取，
   不需要将 `/api/v1/mobile/pairing` 开放给公网。隧道入口还须使用 Access
   等用户身份验证及速率限制；切勿使用无认证的公开 Quick Tunnel。
3. HTTPS 反向代理必须正确向**受信任的** ASGI 运行时传递 scheme=https；
   本服务不信任客户端自行发送的 `X-Forwarded-Proto`。如果反向代理配置不当，
   页面只会显示「请通过 HTTPS 私有入口访问」，不可降低此保护要求。
4. 建议代理侧继续使用身份认证和速率限制；本地登录还包含按连接来源计算的
   5 次失败/5 分钟限制。手机会话只保存在 Mac Core 内存，不新增 SQLite 表。
5. 运行中的 Core 设备 Token 只能由已经认证的 Windows MacCoreClient 使用。
   **绝不**把此 Token 放在 URL、网页源码、浏览器 JS、二维码或公网网页配置中。
6. 当前配对操作证明「已经持有设备凭证」，**不构成可信 Owner 身份验证**。
   因此这套会话永久限定为只读；将来开放危险按钮必须另接 OwnerPrincipal、
   任务与资产 SHA 绑定及 GPU 授权，不能复用普通手机会话代替审批。

## 本机验证

完整 Mac Python CI、Windows WPF/native 构建和以下负向回归必须通过：
默认关闭；不带 Bearer 不可生成配对码；HTTP 手机登录失败；错误 Origin
拒绝；配对码一次性消费和限流；安全 Cookie；日志不泄露配对码；HTML 转义；
未配对用户不可读取剧集和任务；StoryPack 预览不创建 SQLite task / GPU POST。

已有 Mac Core、Windows Worker、SQLite、ComfyUI、Blockout 与 GPU HOLD
保持原样。**不安装第二个网页后端、不新增生产队列和常驻 Agent。**

## 下一个增量

在完成真实 HTTPS 手机访问验收后，继续新增：
候选素材缩略图列表 → 简单 pick/reject → 有限抽卡批次 → 精确镜头返工。
该增量需要专用的移动端权限及可靠的 QC/Owner 门禁，不能靠手机只读会话
直接修改生产数据。
