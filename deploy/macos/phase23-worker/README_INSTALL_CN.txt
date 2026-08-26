Picotoo Pet V2 — Phase 2.3 Slice D / Goal Center E2E Mac Worker 安装说明

适用设备：Apple Silicon M4 / arm64
前置条件：Mac Core 已安装且可通过健康检查；建议先安装同批次 Slice D Core 包。

本包会：
1. 校验发布清单、文件大小、SHA-256、架构和唯一项目 wheel；
2. 直接打开项目 wheel，验证自主情报模块、Connected Intake Autopilot、Frugal Coding Escalation、Codex/Claude Code bounded adapter 和固定 Web GPT Prompt 确实随包交付；
3. 使用包内 wheelhouse 离线安装同批次 Core + Worker Runtime；
4. 在临时端口验证候选 Core、Worker 状态 API 和诊断固定端点；
5. 备份现有 Worker LaunchAgent 定义和 current 指针；
6. 原子切换 current；
7. 写入当前用户的 com.picotoopet.worker LaunchAgent；
8. 启动 Worker，并验证固定支持类型和空闲状态；
9. 提供独立 VERIFY_GOAL_CENTER_E2E.command，用于实机严格判断 Research Gateway、本地模型、Goal 自动分析与 Handoff 动态链是否同时就绪；
10. 提供独立 VERIFY_CODING_PROVIDERS.command，只读报告 Codex 与 Claude Code readiness，不执行 Provider、不读取账号余额/Usage、不自动登录。

Goal Center / Autonomous Intelligence 能力：
- Windows 只提交高层 Goal，不选择底层 task type，也不执行爬虫或 shell；
- Mac Core 是 Goal、任务、结果、证据和审计的唯一事实源；
- Mac Worker 在真实依赖健康时动态注册 autonomous.discovery.v1、autonomous.goal_synthesis.v1、autonomous.goal_handoff.v1；
- autonomous.discovery.v1 只有在 Research Gateway readiness 与本地 Scout 同时健康时才会注册；
- Content Discovery 会自动按当前任务目标生成研究查询，不再只使用固定通用关键词；
- Browser Bridge 成功接入新的规范化证据后，Mac Core 会自动创建一个 P2、产品可见、只读的 research-to-video Goal；不需要用户再手工创建第二个分析任务；
- Maotai OS 4.1 成功导入后，Mac Core 会把该备份内全部已导入 canonical products 自动按每批最多 8 个拆成若干 P2 Goal，直到该导入的安全产品上限全部覆盖；不会只处理前 8 个；
- 每个自动 Goal 仍复用 discovery → local synthesis → handoff 三段冻结链路，只把 Mac Core 已确认的 canonical product keys 作为精确证据作用域；外部程序不能指定 task type、provider、prompt、shell 或账号写操作；
- Browser capture 使用单事件确定性幂等键；4.1 每个产品批次也使用稳定批次幂等键。重复提交同一 capture / 同一备份不会重复生成 Goal；如果中途某一批排队失败，重试只补齐缺失批次；
- 迁移 Maotai OS 4.1 的确定性信息增益、采集节奏和来源策略算法，但不迁移旧 UI 或旧数据库事实源；
- 提供只读 Browser Broker 公开页面采集合同；它只接受经过安全校验的公开页面证据，不读取 Cookie、密码、Token、浏览器存储或支付信息；
- 固定 Web GPT Prompt 会随 Python wheel 一起交付，用于后续人工把交接包提交给网页 ChatGPT；程序不会登录或控制网页 ChatGPT；
- 日常使用不需要打开旧 4.1 UI；
- 旧 4.1 数据库不是事实源，Mac Core 仍是任务、结果和审计的唯一事实源。

Frugal Coding Escalation / 抠门升级仲裁：
- 只对 coding/repo-maintenance/self-repair/technical-diagnosis 类 Goal 有资格考虑 Codex 或 Claude Code；普通研究、内容、视频创意不会进入 coding provider；
- Mac Core 先使用本地分数、保守置信带、验证/测试结果与历史 Wilson 95% 下界决定是否值得外部升级；本地把握足够时明确保持 LOCAL_ONLY；
- Windows 只能读取本地分数、置信带、原因、候选效用和 chosen provider，不能强制选择 provider、模型、预算、argv 或增加 session cap；
- 默认每个 Goal 最多 1 次外部 coding session；只有首家结果本地验证失败/不确定、任务影响较高且预算仍允许时，才可能选择第二家；绝对上限 2，自动重试 0，并发 1；
- Codex 和 Claude Code 都复用隔离 worktree、文件路径/大小/数量限制、immutable Return 和本地验证；不会自动 commit/push/PR/merge/tag/release；
- Claude Code 禁止 Bash、WebFetch、WebSearch、MCP/agent spawning，也禁止 --dangerously-skip-permissions；
- Codex / Claude Code 是否已安装和登录只通过 non-secret readiness 投影判断。程序不会读取 credential 文件、自动安装、自动升级、自动登录、购买套餐、充值或扩大预算。

Worker 固定支持的基础任务：
- system.noop
- system.diagnostic_snapshot

自主情报基础能力清单：
- content.discovery
- objective.query.planning
- browser.capture.contract（能力合同，不是任意浏览器控制任务）

系统诊断任务：
- 只读取 Core/Worker/Queue 的非敏感公开状态；
- 不读取文件清单、日志正文、Token、IP、项目内容或用户文档；
- 不访问网络，不调用 Provider，不产生费用；
- 结果为固定 JSON 合同，最大 64 KiB；
- 单任务执行，硬超时 30 秒；
- 取消或超时后最多等待 5 秒清理子进程，随后强制回收；
- 不领取或改写历史 analysis 任务。

严格实机 Goal Center 验收：
- VERIFY_MAC_WORKER_SLICE_C.command 负责基础安装/Worker 验证，可在离线 fixture 中验证包生命周期；
- VERIFY_GOAL_CENTER_E2E.command 只用于真实 Mac，不允许 fixture 降级；
- 它会确认动态 discovery + synthesis + handoff 三段已经同时进入 Worker 支持类型；
- 它会确认 Goal Center 模板、Goal、详情、Handoff、下载和固定 Prompt 路由真实存在；
- 它只访问 127.0.0.1 与本地 Worker 状态，不创建测试 Goal，不发起一次联网调研，不消耗搜索额度。

严格实机 Coding Provider readiness 验收：
- VERIFY_CODING_PROVIDERS.command 只访问 127.0.0.1 Core readiness API，不直接执行 codex 或 claude 命令；
- 分别输出 CODEX_READINESS 和 CLAUDE_CODE_READINESS，合法值只有 ready / not_authenticated / unavailable / policy_blocked；
- not_authenticated / unavailable 不是安装器自动修复事项；需要安装或登录时必须由用户在实机自行决定和完成；
- readiness 检查不会读取账号余额、Usage、凭据文件，也不会创建 Handoff、Provider Session 或触发费用；
- 看到 PHASE23_CODING_PROVIDER_READINESS_CHECK=PASS 只代表 readiness API 合同与只读探测链正常，不代表两家 Provider 都已经登录。

本包不会：
- 使用 sudo；
- 修改防火墙或系统 LaunchDaemon；
- 删除数据库、Token、日志、结果或旧版本；
- 在用户电脑编译源码或联网解析依赖；
- 动态加载任意任务处理器；
- 把旧 Maotai OS 4.1 SQLite 启动为第二套在线事实源；
- 自动登录网页 ChatGPT、Codex、Claude Code、Amazon、TikTok 或其它需要账号的平台；
- 自动点赞、关注、评论、发帖、私信、收藏、下单或修改账户资料；
- 自动购买 Provider 额度、充值或读取机密账户余额；
- 绕过 Natural Motion V2 真实素材 gate。

安装：双击 INSTALL_MAC_WORKER_SLICE_C.command
基础验证：安装 PASS 后双击 VERIFY_MAC_WORKER_SLICE_C.command
自动链就绪验收：基础验证 PASS 后双击 VERIFY_GOAL_CENTER_E2E.command
Coding Provider readiness：需要确认 Codex/Claude Code 实机状态时双击 VERIFY_CODING_PROVIDERS.command
回滚：仅在验证失败或 Core/Worker 异常时，双击 ROLLBACK_MAC_WORKER_SLICE_C.command

报告目录：
~/Library/Application Support/PicotooPetV2/reports

看到以下三个标记才算“安装成功且 Goal Center 自动链真正就绪”：
PHASE23_MAC_WORKER_SLICE_D_INSTALL=PASS
PHASE23_MAC_WORKER_SLICE_D_VERIFY=PASS
PHASE23_GOAL_CENTER_E2E_READY=PASS

Coding Provider 独立 readiness 合同通过时另外看到：
PHASE23_CODING_PROVIDER_READINESS_CHECK=PASS
CODEX_READINESS=<ready|not_authenticated|unavailable|policy_blocked>
CLAUDE_CODE_READINESS=<ready|not_authenticated|unavailable|policy_blocked>
AUTHENTICATION_USER_ACTION_REQUIRED=true

如果前两个安装标记 PASS、第三个 Goal Center 标记失败，说明程序已安装，但 Research Gateway 或本地模型当前未达到 Goal 自动链健康门；不要重装或删除数据，应按错误提示检查对应依赖。
如果 Coding Provider readiness 是 not_authenticated 或 unavailable，也不要删除数据库或重装 PicotooPet；只有当你确实希望启用该外部 coding provider 时，才需要在 Mac 实机完成对应工具的安装/登录。

安装、验证或回滚任一步失败时，请保留报告文件，不要删除版本目录或数据库。
