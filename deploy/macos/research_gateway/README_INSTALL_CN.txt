PicotooPet Research Gateway 2.3.27.1
====================================

用途
----
这是独立于 Mac Core 的只读 Research Gateway。它负责把 Windows/Goal Center 的研究请求路由到固定、受控的研究工具，并把结果交回 Mac Core 的任务/证据/结果体系。

当前研究工具层
--------------
- Exa：通用 Web 搜索发现（经 mcporter）。
- Crawl4AI：PicotooPet 自有、私有 venv + 私有 Chromium 的公共网页抓取 provider；默认优先。
- Scrapling：公共网页静态/动态抓取与 Crawl4AI 的有限 fallback。
- Thunderbit：结构化抽取的付费后端；只有显式批准时才允许调用，验证器不会自动消耗 credits。
- OpenCLI / Agent Reach：Reddit、Twitter/X、小红书、Facebook、Instagram、雪球等社区/平台只读研究与 Browser Bridge 健康检查。
- GitHub CLI、yt-dlp、bili、curl/Jina：代码、视频、字幕和公共网页读取。

评论/商品研究
-------------
之前 Maotai 商品研究助手的“按星级继续采集评论”能力没有废弃。

Amazon、TikTok 等需要已登录浏览器会话的页面不会交给无会话 Crawl4AI 强行抓取。正确路径是：

  Research Chrome Profile / Browser Bridge
  -> capture_batch_v4 / visible_signals
  -> Mac Core /api/v1/autonomous/browser-captures
  -> canonical evidence 去重、评分/评论字段保留
  -> autonomous.discovery.v1 / local Scout 分析

Browser Bridge 的公开评论批次可以保留 rating、review text、source_id/stable_key、date、author、source_url、verified、signal_kind=review。Mac Core 负责持久化、幂等去重、后续分析与进度，不读取 Cookie、Token、localStorage 或 sessionStorage。

普通公开商品/评论页则可以由 Research Gateway 自动走 Exa -> Crawl4AI -> Scrapling 的受控链路。

安装
----
1. 解压本安装包。
2. 双击 INSTALL_RESEARCH_GATEWAY.command。
3. 安装器会把 Research Gateway 安装到：
   ~/Library/Application Support/PicotooPet/ResearchGateway
4. PicotooPet 自有 Crawl4AI 会安装到独立目录：
   ~/.local/share/picotoopet/research/crawl4ai
   它不会进入 Mac Core/Worker 的 Python 环境。
5. 如果第一次安装 Crawl4AI，安装器会在该私有目录创建 venv，并安装批准版本 crawl4ai==0.9.2 与私有 Playwright Chromium。
6. Agent Reach、OpenCLI、mcporter、Scrapling、Thunderbit、GitHub CLI 等共享工具只检测/绑定，不自动升级、不覆盖现有登录态。
7. 安装不会导入、复制或打包 Chrome/OpenCLI 的 Cookie、Token 或密码。

完整验证
--------
双击 VERIFY_RESEARCH_GATEWAY.command。

验证器只执行只读测试，会检查：
- Gateway 2.3.27.1 / read-only 合同；
- Agent Reach、OpenCLI、mcporter、gh、yt-dlp、bili、curl；
- opencli doctor、agent-reach doctor、GitHub auth；
- Exa research.search 实际调用；
- Jina/curl 公共网页读取；
- Crawl4AI 对 https://example.com 的真实公共页抓取；
- Scrapling 静态网页抓取；
- GitHub 搜索、YouTube 搜索；
- Reddit、Twitter/X、小红书、Facebook、Instagram、雪球各 1 条只读查询；
- Thunderbit 本地绑定。

Thunderbit 的真实结构化调用会消耗 credits，因此完整验证只检查绑定，并明确输出 SKIP thunderbit-paid-call；不会擅自花钱。

安全边界
--------
- 只开放固定 research.* 读取能力。
- 不接受任意 Shell 命令。
- 不自动导出浏览器 Cookie、Token、密码、支付信息或 Browser Storage。
- 不自动发帖、回复、点赞、关注、删除或私信。
- Amazon/TikTok 的已登录采集只能经 Browser Bridge 传回经过清洗的公开证据。
- Mac Core 继续是唯一事实源；Research Gateway/Crawl4AI/OpenCLI 都不是第二套业务数据库。
- Xiaoyuzhou 当前仍未包含在此版本。

卸载
----
双击 UNINSTALL_RESEARCH_GATEWAY.command 可移除 Research Gateway 本体。共享 Homebrew/pipx/npm 工具不会被删除。PicotooPet 私有 Crawl4AI 目录也不会被卸载器误删共享环境；如需专门清理应使用对应 Crawl4AI adapter 卸载流程。
