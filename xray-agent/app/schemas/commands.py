"""Command schemas."""
from pydantic import BaseModel, Field


class CommandRequest(BaseModel):
    """Command request schema."""

    command: str = Field(..., description="Command: add_user, remove_user, regenerate_user, or restart_xray")
    user_uuid: str | None = Field(None, description="UUID пользователя (не требуется для restart_xray)")
    old_user_uuid: str | None = Field(None, description="Старый UUID пользователя (требуется для regenerate_user)")
    email: str | None = Field(None, description="Email пользователя (опционально)")
