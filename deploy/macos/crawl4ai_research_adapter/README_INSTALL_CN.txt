PicotooPet Crawl4AI Research Adapter（Mac arm64）
================================================

用途
----
本包只给 Mac Research Worker / Research Gateway 增加一个隔离的 Crawl4AI crawler provider。
Windows Control Center、Mac Core、Mac Worker 任务模型、Results Center、茅台桌宠和 Windows UI 都不在本包修改范围内。

上层能力保持不变：Windows / Mac Core / Mac Worker 仍然只认识 research.search。
Crawl4AI 与 Scrapling 只存在于 Research Gateway 内部 provider registry。

真实路由顺序
------------
1. research.search 先走既有固定搜索发现入口，得到有限数量的公开 HTTP(S) URL。
2. 普通文章、文档、新闻、博客优先由 Crawl4AI 读取，输出清洗后的 Markdown、title、url、source、status_code。
3. Crawl4AI 单页读取失败且不是 CAPTCHA 情况时，最多执行一次 Scrapling fallback。
4. Crawl4AI 成功后绝不再同时执行 Scrapling。
5. 两个 provider 都失败时返回受控失败，不递归、不无限重试。
6. 新 adapter 的 Scrapling fallback 只使用已批准的 scrapling.get / scrapling.fetch；不会自动升级为 stealth 来绕过挑战。

默认安全上限
------------
maximum pages:         3
maximum depth:         0
page timeout:          30 秒
maximum content bytes: 262144 bytes
redirect limit:        5
concurrency:           2
retry limit:           1

安装隔离
--------
默认 adapter 根目录：
~/.local/share/picotoopet/research/crawl4ai

本包要求可用 Python 3.12 或 3.13；安装器只检测版本，不安装、不升级系统 Python。
macOS 自带 /usr/bin/python3 可能仍是 Python 3.9，因此安装器不会直接采用 PATH 中第一个 python3，而会验证候选解释器版本。
默认候选顺序包括：显式 PICOTOOPET_PYTHON_BIN、已有 adapter 私有 venv、python3.13、python3.12、Apple Silicon Homebrew 常见路径、python.org Framework 常见路径，最后才验证通用 python3。
如果通用 python3 是 3.9，但机器上已经有兼容的 Homebrew/python.org Python 3.12/3.13，安装器会自动选择兼容解释器，不要求修改系统 Python。
如果兼容 Python 安装在其它路径，可设置 PICOTOOPET_PYTHON_BIN=/完整路径/python3 后重新运行安装器。
如果机器只有旧 Python，安装器会打印当前 python3 路径与版本并受控退出；crawl4ai.3 修复了 macOS Bash 3.2 在该诊断分支上的变量边界问题。

首次安装在 adapter 根目录创建私有 Python venv，并固定安装 Crawl4AI 0.9.2。
Playwright Chromium 也安装到 adapter 私有 PLAYWRIGHT_BROWSERS_PATH，不使用系统 Chrome profile。

如果 adapter 私有 venv 已存在且 Crawl4AI 属于批准的 0.9.x，安装器只绑定并保留它，不自动 upgrade/downgrade。
如果检测到不兼容或未知残缺环境，安装器会受控失败，不覆盖它。

安装器只检测现有：
- Python 3.12-3.13（验证候选解释器，不修改系统 python3）
- Docker（仅记录是否存在，本方案默认不依赖 Docker）
- Crawl4AI adapter 私有环境
- Scrapling / scrapling-mcp-local
- Research Gateway 2.3.27.1
- Mac Worker runtime / com.picotoopet.worker

本包不会顺手升级：Python、Node、Scrapling、Chrome、系统 Playwright、ComfyUI 或 PicotooPet 其它依赖。
不使用 sudo，不向系统 Python 安装包。

入口
----
INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command
  安装/重复安装兼容 adapter，并记录 install-state.json 与安装日志。

VERIFY_CRAWL4AI_RESEARCH_ADAPTER.command
  默认执行真实静态页、JS 页、Markdown/metadata、HTTP 404、真实延迟 timeout、DNS 网络失败、正文大小限制验证，并写 verification evidence。

ROLLBACK_CRAWL4AI_RESEARCH_ADAPTER.command
  恢复 gateway.py.pre-crawl4ai，只删除 adapter 自己拥有的 wrapper/runtime/data；只有首次由本包创建的 venv/Chromium 才会删除。
  Scrapling、Research Gateway 根目录、Mac Worker 与 Chrome 登录状态不会删除。

明确禁止的能力
--------------
本次 Research/Crawler 仍然只有 search / open / read / crawl / extract。

以下全部禁止：
- CAPTCHA bypass / CAPTCHA 绕过
- 登录、授权登录、偷偷登录网站
- 读取、导出或复用 Chrome cookie / cookies
- 读取密码
- 读取或导出 token
- 改变 Chrome 当前登录状态
- 点赞
- 关注
- 评论
- 发帖
- 私信
- 收藏
- 下单
- 修改账户资料
- 任意账号写操作
- arbitrary shell / 任意命令执行
- 任意脚本执行入口
- 无限深度爬站、无限页面、无限 retry、无限 token 内容

如果未来要实现 social.like / social.follow / social.comment 等写能力，必须另建独立 capability、授权、审计、额度和人工确认；本 adapter 不包含这些能力。

Crawl4AI attribution
--------------------
This project uses Crawl4AI (https://github.com/unclecode/crawl4ai) for web data extraction.

版本
----
PicotooPet Research Gateway baseline: 2.3.27.1
Crawl4AI adapter: 2.3.27.1-crawl4ai.3
Fresh isolated Crawl4AI pin: 0.9.2
Compatible Python: 3.12-3.13
Target: macOS arm64
