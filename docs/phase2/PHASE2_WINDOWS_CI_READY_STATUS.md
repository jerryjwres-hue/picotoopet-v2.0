# Phase 2 Windows CI 就绪状态

## 当前结论

Windows Desktop 源码已改造成“原生 Windows CI 构建、用户电脑只安装预编译文件”的交付方式。

当前 Linux 执行环境已经完成：

- 修复 `MacCoreClient.cs` 的 `EndsWith('/')` 编译问题；
- 增加 WPF 主程序 `--self-test` 无界面自检；
- 增加诊断器 `--self-test`；
- 增加 Windows Server 2025 GitHub Actions 工作流；
- 固定 .NET SDK `10.0.302`；
- 增加 `WarningsAsErrors` 原生构建门禁；
- 增加 win-x64 self-contained single-file 发布；
- 增加发布清单、文件大小和 SHA-256；
- 增加 ZIP 解压后复验；
- 增加 Windows PowerShell 5.1 脚本解析门禁；
- 增加预编译安装器的可见进度、原子激活、失败恢复和明确退出码；
- 禁止用户安装器调用 `dotnet`、`winget` 或任何 `.csproj`。

## 已完成验证

```text
Python 回归：141 passed
发布扫描：pass
秘密发现：0
PowerShell BOM 错误：0
预编译交付契约：9 passed
```

## 仍需原生 Windows CI 完成的门禁

以下结果不能由当前 Linux 环境代替：

1. .NET SDK 10.0.302 原生 restore/build；
2. C# 14 与 .NET 10 分析器零警告编译；
3. WPF win-x64 publish；
4. `Picotoo Pet AI.exe --self-test`；
5. `PicotooPet.Desktop.Diagnostics.exe --self-test`；
6. Windows PowerShell 5.1 语法解析；
7. 发布 ZIP 解压、哈希和进程退出门禁。

只有 GitHub Actions `Native Windows build and release gate` 为绿色时，生成的 Artifact 才允许交给用户安装。

## 当前外部依赖

ChatGPT 的 GitHub 连接当前没有可访问仓库，因此工作流尚未运行。下一步需要一个空的私有 GitHub 仓库，并将该仓库授权给当前 GitHub 连接。
