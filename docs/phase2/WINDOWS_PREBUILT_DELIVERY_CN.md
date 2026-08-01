# Phase 2 Windows 预编译交付链路

## 目的

用户电脑不再执行 `dotnet restore/build/publish`，也不再安装 SDK。所有 C# 编译、分析器、WPF 启动自检和安装包校验必须先在原生 Windows CI 中完成。

## 固定流程

```text
GitHub Windows Server 2025 runner
→ .NET SDK 10.0.302
→ restore
→ build（WarningsAsErrors）
→ Core Smoke Tests
→ win-x64 self-contained single-file publish
→ Desktop --self-test
→ Diagnostics --self-test
→ 生成 release-manifest.json
→ SHA-256 全文件校验
→ PowerShell 5.1 语法门禁
→ ZIP 重新解压复验
→ 上传预编译安装包
```

## 用户电脑安装行为

安装器只进行：

1. 校验预编译发布清单；
2. 校验 payload 全部 SHA-256；
3. 复制到版本暂存目录；
4. 再次校验；
5. 原子激活版本指针；
6. 创建开始菜单和开机快捷方式；
7. 启动程序并检查是否立即退出；
8. 输出明确的 `pass` 或 `fail` 报告并退出。

安装器不会：

- 安装 .NET SDK；
- 在用户电脑编译源码；
- 修改 ComfyUI 或视觉模型；
- 修改 Mac Core 数据库；
- 读取或修改 Protected 数据。

## 发布门槛

只有 GitHub Actions 的 `Native Windows build and release gate` 成功，才允许下载并交付 Actions Artifact。当前本地 Linux 环境只能验证包结构和脚本契约，不能替代 Windows CI 结论。
