# Mac 本机 Owner 审核（运维工具）

用途：StoryPack / 纯宠物 v2 创意 Goal 会停在 `creative.content_plan.v2 · Ready`，直到 Owner
在本机审核并提交主人事实（Owner commitment）。Windows 端的加密审核通道仍是 `BLOCKED`
（`PinnedSshStdioActivated=false`），本工具**不改变它**，也不是 Windows 日常界面。

边界：只在 Mac mini 上、由 Owner 本人在自己的登录会话中运行；只访问
`http://127.0.0.1:<端口>` 上现有的 loopback-only Owner 审核 API；不改数据库、不建任务、
不碰 GPU / HOLD；密钥只存在本机钥匙串，从不显示、不写文件、不进命令行参数。

## 一次性准备（Owner 本人执行）

```bash
cd <仓库或解压目录>
/usr/bin/python3 scripts/mac/owner_review/owner_review_local.py provision \
  --credential-id owner-maotai-1 --actor-id owner-dsfed --subject pet:maotai
```

输出 `OWNER_REVIEW_PROVISIONED=PASS` 即成功；登记表默认在
`~/Library/Application Support/PicotooPetV2/owner-review-registry.json`（0600）。

让 Mac Core 读取登记表并重启（重新安装 Core 后需再次执行）：

```bash
PLIST=~/Library/LaunchAgents/com.picotoopet.mac-core.plist
REG="$HOME/Library/Application Support/PicotooPetV2/owner-review-registry.json"
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables dict" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Delete :EnvironmentVariables:PICOTOO_OWNER_REVIEW_REGISTRY_FILE" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:PICOTOO_OWNER_REVIEW_REGISTRY_FILE string $REG" "$PLIST"
launchctl bootout gui/$(id -u)/com.picotoopet.mac-core
launchctl bootstrap gui/$(id -u) "$PLIST"
```

## 审核一个 Goal

```bash
/usr/bin/python3 scripts/mac/owner_review/owner_review_local.py review \
  --goal-id <goal_id> --credential-id owner-maotai-1 [--base-url http://127.0.0.1:<Core 端口，如 8766>]
```

- `EXPLICIT` 字段（有来源证据）默认确认；`UNKNOWN/CONFLICT` 字段逐个选择：更正（输入 JSON 值）或保持未知。
- 有动态动作提案时需输入 `y` 才会确认那一个 `motion_digest`；否则可选静态宠物故事策略。
- 预览不是 `READY` 时不会提交；是 `READY` 时只有输入「确认提交」才提交。
- 成功输出 `OWNER_REVIEW_COMMITTED=PASS`，Core 随后为该 Goal 排入 Creative 执行任务。

撤销：从登记表删除该 credential 或把 `enabled` 改为 `false`，删除钥匙串条目
`PicotooPetV2.OwnerReview.<credential_id>`，再按上面方式重启 Core。
