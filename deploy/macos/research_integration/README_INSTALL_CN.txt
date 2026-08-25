PicotooPet Research 2.3.27.1 — Mac Apple Silicon
=================================================

这是什么
--------
这是 PicotooPet 2.3.27.1 的 Mac 一体化 Research 更新包，不只是一个独立 Gateway 文件夹。
安装完成后：Windows 创建 research.search → Mac Core 入队 → Mac Worker 调用独立 Research Gateway → 结果回到现有 ResultStore/任务体系。
同时保留 Maotai 旧评论采集器的 5/4/3/2/1 星定向评论输入，重复扫描由 Mac Core canonical evidence 去重。

安装
----
1. 保持现有 Mac Core/Worker 已正常运行。
2. 不需要重新安装 Agent Reach、OpenCLI、Scrapling、Thunderbit，也不要删除浏览器登录态。
3. 双击 INSTALL_PICOTOOPET_RESEARCH_2_3_27_1.command。
4. 安装器会在 PicotooPet 私有目录安装/复用 Crawl4AI 0.9.x + 私有 Playwright Chromium；它不进入 Mac Core venv，也不读取日常 Chrome Profile/Cookie。
5. 安装器先绑定独立 Research Gateway，再通过现有原子升级机制更新 Mac Core/Worker。
6. 安装结束会自动执行组合验证：Worker 必须真实注册 research.search，并对已接入 Research 工具执行限量只读 smoke。

验证
----
双击 VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command。
它会确认：
- Research Gateway 版本为 2.3.27.1，且保持 read-only；
- Mac Core/Worker 产品版本与安装包一致；
- Worker 在线并真实注册 research.search；
- Exa/search、公共网页读取、Crawl4AI、Scrapling、GitHub、YouTube 的真实只读调用；
- 已接入 OpenCLI 渠道 Reddit、Twitter/X、小红书、Facebook、Instagram、雪球的限量只读查询；
- Agent Reach/OpenCLI doctor 与 GitHub auth 状态；
- Thunderbit 只验证绑定，不会为了测试自动消耗 credits。

Amazon/TikTok 等依赖登录会话的商品/评论采集仍由 Browser Bridge 执行；Core 只接收清洗后的公共数据，不读取 Cookie、Token、密码或支付信息。

回滚
----
双击 ROLLBACK_PICOTOOPET_RESEARCH_2_3_27_1.command。
它只把 Core/Worker 原子切回安装前版本，不删除独立 Gateway，也不删除/升级 Agent Reach、OpenCLI、Scrapling、Thunderbit、Node、Chrome 扩展或浏览器登录态。
Crawl4AI 属于 PicotooPet 私有 Research provider；其私有目录与共享工具链相互隔离。

安全边界
--------
- 2.3.27.1 Windows 直接开放的 Research 任务是 research.search，只读执行。
- Windows 不获得 Shell 权限，也不会直接调用 OpenCLI、mcporter 或其他 Mac 命令。
- Core 会再次校验 query/limit 并冻结 priority、resource_tag、重试、超时与 local_only 策略。
- 发帖、回复、点赞、关注、删除、私信等写操作不在本安装包能力面内。
- 不新增第二套任务数据库；Mac Core/SQLite 继续是事实源。
