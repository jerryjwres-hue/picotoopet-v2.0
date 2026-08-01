"""受控根目录、路径穿越和符号链接防护。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathAccessError(PermissionError):
    """路径不在允许边界内。"""


def _normalise_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(Path(root).expanduser().resolve() for root in roots)


@dataclass(frozen=True, slots=True)
class PathPolicy:
    managed_roots: tuple[Path, ...]
    protected_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "managed_roots", _normalise_roots(self.managed_roots))
        object.__setattr__(self, "protected_roots", _normalise_roots(self.protected_roots))

    @staticmethod
    def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
        return any(path == root or path.is_relative_to(root) for root in roots)

    def resolve_and_check(self, candidate: Path | str, *, for_write: bool) -> Path:
        """解析真实路径并强制根目录边界。"""

        resolved = Path(candidate).expanduser().resolve(strict=False)

        if for_write and self._inside(resolved, self.protected_roots):
            raise PathAccessError("Protected 路径禁止写入。")
        if for_write and not self._inside(resolved, self.managed_roots):
            raise PathAccessError("写入路径不在 V2 受控根目录。")
        if not for_write and not (
            self._inside(resolved, self.managed_roots)
            or self._inside(resolved, self.protected_roots)
        ):
            raise PathAccessError("读取路径不在授权根目录。")
        return resolved
