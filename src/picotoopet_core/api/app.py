"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from picotoopet_core import __version__
from picotoopet_core.api.middleware import TraceTimingMiddleware
from picotoopet_core.config.models import AppSettings
from picotoopet_core.services import build_services
from picotoopet_core.mobile.access import MobileAccess
from picotoopet_core.domain.frame_transfer_tickets import FrameTransferTickets

from .errors import install_error_handlers
from .routes import (
    approvals,
    episodes,
    events,
    executors,
    frame_transfers,
    health,
    mobile,
    history_imports,
    projects,
    results,
    status,
    studio,
    studio_owner_review,
    studio_master_review,
    tasks,
)


def create_app(settings: AppSettings) -> FastAPI:
    """创建已迁移数据库和统一路由的 Mac Core 应用。"""

    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        stop_event         = asyncio.Event()
        dispatcher_task    = asyncio.create_task(
            services.dispatcher.run(stop_event),
            name="picotoo-outbox-dispatcher",
        )
        try:
            yield
        finally:
            stop_event.set()
            await dispatcher_task
            services.close()
            app.state.frame_transfer_tickets.close()

    app = FastAPI(
        title="Picotoo Pet Mac Core",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.services = services
    # 单进程短效传输凭据；重启即失效，不创建新数据库或服务。
    app.state.frame_transfer_tickets = FrameTransferTickets()
    app.state.mobile_access = MobileAccess()        # 仅进程内，Core 重启需重新手机配对。
    app.add_middleware(TraceTimingMiddleware)
    install_error_handlers(app)
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix, tags=["health"])
    app.include_router(projects.router, prefix=prefix, tags=["projects"])
    app.include_router(tasks.router, prefix=prefix, tags=["tasks"])
    app.include_router(executors.router, prefix=prefix, tags=["executors"])
    app.include_router(episodes.router, prefix=prefix, tags=["episodes"])
    app.include_router(studio.router, prefix=prefix, tags=["studio"])
    app.include_router(frame_transfers.router, prefix=prefix, tags=["frame-transfer"])
    # 独立 Owner 凭据和本机来源认证，不能被设备 Bearer 替代。
    app.include_router(studio_owner_review.router, prefix=prefix, tags=["studio-owner-review"])
    # 独立 MASTER 审查仍使用现有 Core、审计链与 loopback 身份门禁。
    app.include_router(studio_master_review.router, prefix=prefix, tags=["studio-master-review"])
    app.include_router(mobile.router, tags=["mobile"])
    app.include_router(history_imports.router, prefix=prefix, tags=["episodes"])
    app.include_router(approvals.router, prefix=prefix, tags=["approvals"])
    app.include_router(results.router, prefix=prefix, tags=["results"])
    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(status.router, prefix=prefix, tags=["status", "audit"])
    return app
