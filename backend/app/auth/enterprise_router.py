from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import get_settings
from app.deps import AdminDep

router = APIRouter(prefix="/admin/identity", tags=["auth"])


class AdapterStatus(BaseModel):
    provider: str
    configured: bool
    enabled: bool
    detail: str


@router.get("/saml/status", response_model=AdapterStatus)
async def saml_status(_: AdminDep) -> AdapterStatus:
    settings = get_settings()
    configured = bool(settings.saml_metadata_url and settings.saml_entity_id and settings.saml_acs_url)
    return AdapterStatus(
        provider="saml",
        configured=configured,
        enabled=configured,
        detail="SAML login is available when metadata URL, entity ID, and ACS URL are configured.",
    )


@router.post("/saml/test", response_model=AdapterStatus)
async def saml_test(admin: AdminDep) -> AdapterStatus:
    status_row = await saml_status(admin)
    if not status_row.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SAML is not configured")
    return status_row


@router.get("/ldap/status", response_model=AdapterStatus)
async def ldap_status(_: AdminDep) -> AdapterStatus:
    settings = get_settings()
    configured = bool(settings.ldap_url and settings.ldap_bind_dn and settings.ldap_user_base_dn and settings.ldap_group_base_dn)
    return AdapterStatus(
        provider="ldap",
        configured=configured,
        enabled=configured and settings.ldap_sync_enabled,
        detail="LDAP group sync is enabled only when LDAP settings are configured and LDAP_SYNC_ENABLED=true.",
    )


@router.post("/ldap/sync")
async def ldap_sync(admin: AdminDep) -> dict:
    status_row = await ldap_status(admin)
    if not status_row.enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "LDAP group sync is not enabled")
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "LDAP adapter is configured but no runtime LDAP client is installed")
