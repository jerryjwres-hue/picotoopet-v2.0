PicotooPet Research Gateway 2.3.27.1
====================================

用途
----
这是独立于 Mac Core 的 Research Gateway 更新包。它提供只读 research.* 能力，并把 Agent Reach、OpenCLI、GitHub CLI、Exa、Scrapling、Thunderbit、YouTube/Bilibili 等平台工具隔离在 Research Gateway 进程边界内。

安装
----
1. 解压本安装包。
2. 双击 INSTALL_RESEARCH_GATEWAY.command。
3. 安装器只检测并绑定 Mac 上已经部署的研究工具，不会重新安装或升级它们。
4. 保留你现有的 PicotooPet Research Chrome Profile、OpenCLI Browser Bridge 与登录态。
5. 双击 VERIFY_RESEARCH_GATEWAY.command 查看外部工具与 Browser Bridge 状态。

安全边界
--------
- 2.3.27.1 只开放 research.* 读取能力。
- 不接受任意 Shell 命令。
- 不自动复制、导出或打包浏览器 Cookie。
- 不安装或升级 Node、OpenCLI、Agent Reach、Scrapling、Thunderbit 或 Chrome 扩展。
- 写入、发帖、回复、关注、删除、点赞、私信等行为不在本版本能力面内。
- Xiaoyuzhou 未包含在本版本。
- Mac Core 虚拟环境不会安装 Agent Reach/OpenCLI。

卸载
----
双击 UNINSTALL_RESEARCH_GATEWAY.command 可移除 Research Gateway 本体。为避免破坏其他程序，Homebrew、pipx、npm 安装的共享依赖不会自动删除。
