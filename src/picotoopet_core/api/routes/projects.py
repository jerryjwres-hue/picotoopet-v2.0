"""项目 REST 路由。"""

from fastapi import APIRouter, Depends, Request, status

from picotoopet_core.domain.models import ProjectCreate, ProjectRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/projects", response_model=ProjectRecord, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request) -> ProjectRecord:
    """创建项目元数据。"""

    return request.app.state.services.projects.create(payload)


@router.get("/projects", response_model=list[ProjectRecord])
def list_projects(request: Request) -> list[ProjectRecord]:
    """列出项目。"""

    return request.app.state.services.projects.list()


@router.get("/projects/{project_id}", response_model=ProjectRecord)
def get_project(project_id: str, request: Request) -> ProjectRecord:
    """读取指定项目。"""

    return request.app.state.services.projects.get(project_id)
