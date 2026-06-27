from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUserDep
from app.execution.cancellation import query_registry

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("/{query_id}/cancel")
async def cancel_query(query_id: str, user: CurrentUserDep) -> dict:
    cancelled = query_registry.cancel(query_id, owner_id=str(user.id))
    if not cancelled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "query not found or already finished")
    return {"ok": True, "query_id": query_id, "status": "cancel_requested"}
