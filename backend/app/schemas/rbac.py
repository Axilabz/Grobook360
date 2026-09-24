from pydantic import BaseModel


class PermissionItem(BaseModel):
    id: str
    code: str
    description: str | None


class RoleSummary(BaseModel):
    id: str
    name: str
    description: str | None
    permissions: list[str]


class RoleDetail(RoleSummary):
    user_count: int
