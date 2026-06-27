from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import gateway
from app.deps import CurrentUserDep, SessionDep
from app.settings.models import UserSetting

router = APIRouter(prefix="/settings", tags=["settings"])


class AISettings(BaseModel):
    provider: str = "ollama"
    model: str | None = None
    api_base: str | None = None
    api_key_configured: bool = False
    policy: str = "metadata_only"
    extra: dict[str, Any] = {}


class AISettingsIn(BaseModel):
    provider: str = "ollama"
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    policy: str = "metadata_only"
    extra: dict[str, Any] = {}


def _public(value: dict | None) -> AISettings:
    data = dict(value or {})
    configured = bool(data.get("api_key"))
    data.pop("api_key", None)
    if not data.get("model"):
        data["model"] = gateway.default_model_for(data.get("provider", "ollama"))
    data["api_key_configured"] = configured
    return AISettings(**data)


@router.get("/ai", response_model=AISettings)
async def get_ai_settings(session: SessionDep, user: CurrentUserDep) -> AISettings:
    row = await session.execute(
        select(UserSetting).where(UserSetting.user_id == user.id, UserSetting.setting_key == "ai")
    )
    setting = row.scalar_one_or_none()
    return _public(setting.value if setting else {"provider": "ollama", "model": gateway.default_model_for("ollama")})


@router.put("/ai", response_model=AISettings)
async def put_ai_settings(payload: AISettingsIn, session: SessionDep, user: CurrentUserDep) -> AISettings:
    value = payload.model_dump()
    existing = await session.execute(
        select(UserSetting).where(UserSetting.user_id == user.id, UserSetting.setting_key == "ai")
    )
    setting = existing.scalar_one_or_none()
    if setting is None:
        setting = UserSetting(user_id=user.id, setting_key="ai", value=value)
        session.add(setting)
    else:
        if not value.get("api_key") and isinstance(setting.value, dict) and setting.value.get("api_key"):
            value["api_key"] = setting.value["api_key"]
        setting.value = value
        setting.updated_at = datetime.utcnow()
    await session.commit()
    return _public(setting.value)
