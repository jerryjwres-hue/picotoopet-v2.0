#!/usr/bin/env python3
"""Route the frozen cloud-development contract page, then delete this script."""

from pathlib import Path

path = Path("windows/desktop/src/PicotooPet.Desktop/ViewModels/ShellViewModel.cs")
text = path.read_text(encoding="utf-8")

runtime_anchor = (
    "        NavigationRoute.Settings => new SettingsPageViewModel(snapshot.MacBaseUrl),\n"
)
runtime_replacement = (
    "        NavigationRoute.CloudDevelopment => new CloudDevelopmentPageViewModel(),\n"
    "        NavigationRoute.Settings => new SettingsPageViewModel(snapshot.MacBaseUrl),\n"
)
if text.count(runtime_anchor) != 1:
    raise SystemExit("runtime CloudDevelopment route anchor mismatch")
text = text.replace(runtime_anchor, runtime_replacement, 1)

navigation_old = '''            Item(
                NavigationRoute.CloudDevelopment,
                "云端开发",
                isAvailable: false,
                "当前只冻结 Handoff / Return Contract，未安装或调用外部 Provider。"),
'''
navigation_new = '''            Item(
                NavigationRoute.CloudDevelopment,
                "云端开发",
                isAvailable: true,
                "Handoff / Return Contract v1 已冻结；Provider 尚未配置。"),
'''
if text.count(navigation_old) != 1:
    raise SystemExit("CloudDevelopment navigation item mismatch")
text = text.replace(navigation_old, navigation_new, 1)

static_old = '''        NavigationRoute.CloudDevelopment => new EmptyStatePageViewModel(
            "云端开发",
            "当前版本只冻结了 Handoff / Return Contract，尚未安装或调用外部 Provider。",
            "Phase 10A 将先加入包预览和审批；Phase 10B 才加入 Dev Broker。",
            "你现在不需要操作。"),
'''
static_new = '''        NavigationRoute.CloudDevelopment => new CloudDevelopmentPageViewModel(),
'''
if text.count(static_old) != 1:
    raise SystemExit("static CloudDevelopment route mismatch")
text = text.replace(static_old, static_new, 1)

path.write_text(text, encoding="utf-8")
