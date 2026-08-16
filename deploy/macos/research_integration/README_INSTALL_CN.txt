PicotooPet Research 2.3.27.1 — Mac Apple Silicon
=================================================

这是什么
--------
这是 PicotooPet 2.3.27.1 的 Mac 一体化 Research 更新包，不只是一个独立 Gateway 文件夹。
安装完成后：Windows 创建 research.search → Mac Core 入队 → Mac Worker 调用独立 Research Gateway → 结果回到现有 ResultStore/任务体系。

安装
----
1. 保持现有 Mac Core/Worker 已正常运行。
2. 不需要重新安装 Agent Reach、OpenCLI、Scrapling、Thunderbit，也不要删除浏览器登录态。
3. 双击 INSTALL_PICOTOOPET_RESEARCH_2_3_27_1.command。
4. 安装器先绑定独立 Research Gateway，再通过现有原子升级机制更新 Mac Core/Worker。
5. 安装结束会自动执行组合验证；只有 Worker 真实报告 research.search 才会显示 PASS。

验证
----
双击 VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command。
它会确认：
- Research Gateway 版本为 2.3.27.1；
- Gateway 保持 read-only；
- Xiaoyuzhou 仍未启用；
- research.search 所需 mcporter 可见；
- Mac Core/Worker 产品版本与安装包一致；
- Worker 在线并真实注册 research.search。

回滚
----
双击 ROLLBACK_PICOTOOPET_RESEARCH_2_3_27_1.command。
它只把 Core/Worker 原子切回安装前版本，不删除独立 Gateway，也不删除/升级 Agent Reach、OpenCLI、Scrapling、Thunderbit、Node、Chrome 扩展或浏览器登录态。

安全边界
--------
- 2.3.27.1 Windows 直接开放的 Research 任务是 research.search，只读执行。
- Windows 不获得 Shell 权限，也不会直接调用 OpenCLI、mcporter 或其他 Mac 命令。
- Core 会再次校验 query/limit 并冻结 priority、resource_tag、重试、超时与 local_only 策略。
- 发帖、回复、点赞、关注、删除、私信等写操作不在本安装包能力面内。
- 不新增第二套任务数据库；Mac Core/SQLite 继续是事实源。
