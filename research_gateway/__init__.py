"""PicotooPet standalone Research Gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .gateway import READ_CAPABILITIES, CommandResult, GatewayDispatcher, PolicyError

__all__ = ["READ_CAPABILITIES", "CommandResult", "GatewayDispatcher", "PolicyError"]


def __getattr__(name: str) -> Any:
    """Load gateway exports lazily so ``python -m research_gateway.gateway`` stays single-run."""

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from . import gateway

    return getattr(gateway, name)
