from pathlib import Path

import pytest

from picotoopet_core.permissions.path_policy import PathAccessError, PathPolicy


def test_path_policy_rejects_traversal_outside_managed_root(tmp_path: Path) -> None:
    """路径穿越不得逃出 Workspace。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = PathPolicy(managed_roots=(workspace,), protected_roots=())

    with pytest.raises(PathAccessError):
        policy.resolve_and_check(workspace / ".." / "outside.txt", for_write=True)


def test_path_policy_rejects_symlink_escape(tmp_path: Path) -> None:
    """符号链接不得把写入重定向到受控根目录之外。"""

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    policy = PathPolicy(managed_roots=(workspace,), protected_roots=())

    with pytest.raises(PathAccessError):
        policy.resolve_and_check(workspace / "escape" / "file.txt", for_write=True)
