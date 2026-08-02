# Phase 2.3 安装事故台账与发布门

更新时间：2026-08-02

本文件记录真实 Windows 与 Mac 安装中出现的问题、根因、修复和永久发布门。任何后续安装包不得删除或绕过这些门。

## 适用设备

- Windows：用户电脑只安装 GitHub 原生 Windows CI 生成的预编译包，不编译、不修包。
- Mac：当前目标设备为 Apple Silicon M4，架构固定为 `arm64`；不再为 Intel 构建用户交付包。

## WIN-2026-08-01-UTF8-MANIFEST

### 现场症状

Windows 安装报告在读取 `release-manifest.json` 时失败；`version`、`install_path` 和 payload 哈希均为空，失败发生在激活前。

### 根因

Windows PowerShell 5.1 的 `Get-Content` 默认文本编码受系统区域设置影响。发布清单为 UTF-8 无 BOM，在中文 Windows 上被错误解码，随后 `ConvertFrom-Json` 失败。

### 修复

- 安装、验证、回滚脚本统一使用 `Read-JsonUtf8`。
- JSON 读取使用 `File.ReadAllText(path, UTF8Encoding(false, true))`。
- 安装器增加 `-PreflightOnly`，只验证清单和 payload，不激活版本。
- Windows 原生 CI 对“实际生成的 ZIP”执行 Windows PowerShell 5.1 安装预检。

### 永久发布门

1. 禁止重新引入 `Get-Content -Raw | ConvertFrom-Json` 读取机器 JSON。
2. 严格 UTF-8 测试必须通过。
3. 实际生成包必须执行 `Install-Phase2Prebuilt.ps1 -PreflightOnly`。
4. 预检报告必须为 `pass` 才能上传正式 Artifact。
5. 用户电脑不得构建源码。

## WIN-2026-08-02-DESKTOP-SHORTCUT

### 现场症状

Windows Control Center 已经安装，但桌面没有入口。用户没有保存安装目录，也没有创建快捷方式，因此无法确认如何重新打开之前做好的图形界面。

### 根因

安装器的 `Get-PicotooShortcutPaths` 只包含：

- 开始菜单；
- 开机启动目录。

它没有包含当前用户的 `DesktopDirectory`。因此程序虽然已经安装并设置为登录启动，但用户在桌面上找不到可见入口。

### 修复

- 使用 `[Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)` 获取真实桌面路径，兼容 OneDrive 或系统重定向桌面。
- 每次成功安装同时创建桌面、开始菜单和开机启动三个快捷方式。
- 快捷方式创建后重新读取 `.lnk`，验证目标确实指向当前激活版本的 `Picotoo Pet AI.exe`。
- 安装报告增加 `desktop_shortcut` 和 `desktop_shortcut_created`。
- 快捷方式创建或验证失败时，纳入既有激活回滚事务。
- 提供无需编译的一键桌面快捷方式修复脚本，供已经安装的旧包使用。

### 永久发布门

1. 每个 Windows 安装候选必须包含桌面快捷方式创建逻辑。
2. 必须通过 `tests/contract/test_windows_desktop_shortcut_release_gate.py`。
3. Windows 原生包级安装测试必须验证桌面 `.lnk` 存在且目标正确。
4. 安装报告必须记录 `desktop_shortcut_created=true`。
5. 回滚必须恢复上一版本对应的桌面、开始菜单和开机启动快捷方式。
6. 用户不需要知道版本目录或手工寻找 EXE。

## MAC-2026-08-02-SPACED-RUNTIME-PATH

### 现场症状

M4 Mac 安装器在读取现有 Python 版本时失败，报告中的失败命令为：

```text
python_version="$($current_python --version 2>&1)"
```

失败发生在新版本目录创建和 `current` 切换之前，因此旧 Mac Core 未被替换。

### 根因

真实运行目录包含空格：

```text
~/Library/Application Support/PicotooPetV2
```

可执行文件路径变量未作为一个引用参数调用，Shell 把 `Application Support` 拆成两个参数。此前 CI 临时目录没有空格，导致测试遗漏。

### 修复

- 改为 `python_version="$("$current_python" --version 2>&1)"`。
- 原生安装夹具的运行目录固定包含 `Application Support`。
- M4/arm64 原生 CI 完整验证离线安装、认证 API、历史 `Queued` 保持和回滚。
- 后续只构建 `macos-15 / arm64`，不再运行 Intel 用户交付任务。

### 永久发布门

1. 所有包含路径的命令变量必须作为引用参数调用。
2. 安装夹具必须在含空格目录中运行。
3. 安装、验证、回滚完整夹具必须通过。
4. 历史 `Queued` 任务的状态和 `updated_at` 不得在无 Worker 阶段改变。
5. 用户 Mac 不得联网解析依赖或编译源码。

## 跨平台通用发布规则

每个用户可安装候选必须同时具有：

- 原生平台 CI；
- 包内清单和 SHA-256；
- 对实际生成归档的包级复验；
- 安装报告、验证报告和回滚报告；
- 安装失败时的明确阶段和失败命令；
- 成功 Artifact 与 `DIAGNOSTIC` Artifact 的明确区分；
- `source_build_on_user_pc=false` 或 `source_build_on_user_mac=false`；
- 可恢复的旧版本指针；
- 不删除数据库、Token、日志、结果和旧版本目录；
- 不使用 `sudo`、系统级 LaunchDaemon、防火墙或注册表核心修改。

## 下一阶段继承要求

Mac Worker Runtime 的安装包必须继承以上全部门，并额外验证：

- Worker 默认禁用，只有显式安装并启用后才领取任务；
- 启用前旧 `Queued` 任务保持不变；
- 租约、心跳、取消、超时恢复和幂等终态均有原生 arm64 包级测试；
- Worker 安装失败不得影响 Mac Core API；
- 回滚必须同时恢复 Worker 与 Core 的兼容版本组合。
