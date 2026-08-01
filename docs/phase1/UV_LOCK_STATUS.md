# uv 锁文件状态

当前沙箱无法访问 Python 包索引，且缺少正式运行所需的 `pydantic-ai`、MCP SDK 和 `aiosqlite` 安装缓存，因此不能在此环境中诚实生成可验证的 `uv.lock`。

Mac 安装器采用以下规则：

- 交付包存在 `uv.lock`：执行 `uv sync --frozen`。
- 首次交付不存在 `uv.lock`：在目标 Mac 联网环境执行 `uv lock`，随后立即执行 `uv sync --frozen`。

首次成功安装后，应把生成的 `uv.lock` 保存回后续发布分支。当前 pytest 使用沙箱已安装依赖完成源码验证，但不把该结果冒充为目标 Mac 依赖锁定验证。
