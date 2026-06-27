"""Scheduled dashboard report job with pluggable delivery."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from app.dashboards.models import Dashboard, DashboardComponent
from app.jobs.registry import job_task
from app.storage.fs import default_bucket_uri, get_fs


def _deliver(report: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    dtype = destination.get("type") or "file"
    if dtype == "file":
        uri = destination.get("uri") or default_bucket_uri(f"reports/{report['dashboard_id']}/{report['generated_at']}.json")
        fs = get_fs(uri)
        parent = uri.rsplit("/", 1)[0]
        if parent and not fs.exists(parent):
            fs.makedirs(parent, exist_ok=True)
        with fs.open(uri, "w") as handle:
            json.dump(report, handle, default=str)
        return {"type": "file", "delivered": True, "uri": uri}
    if dtype == "webhook":
        import httpx

        url = destination.get("url")
        if not url:
            raise ValueError("webhook destination requires url")
        with httpx.Client(timeout=20.0) as client:
            response = client.post(url, json=report, headers=destination.get("headers") or {})
            response.raise_for_status()
        return {"type": "webhook", "delivered": True, "status_code": response.status_code}
    if dtype == "email":
        return {"type": "email", "delivered": False, "status": "smtp_not_configured"}
    if dtype == "audit_only":
        return {"type": "audit_only", "delivered": True}
    raise ValueError(f"unsupported report destination type: {dtype}")


@job_task("scheduled_report")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    dashboard_id = input.get("dashboard_id")
    if not dashboard_id:
        raise ValueError("scheduled_report requires dashboard_id")
    dashboard = session.get(Dashboard, uuid.UUID(str(dashboard_id)))
    if dashboard is None:
        raise ValueError(f"Dashboard {dashboard_id} not found")
    if job.user_id is None:
        raise PermissionError("scheduled report requires an owning user")
    from app.permissions.enforcement import require_object_capability_sync
    require_object_capability_sync(session, job.user_id, "dashboard", dashboard.id, "view_data")
    components = session.query(DashboardComponent).filter(
        DashboardComponent.dashboard_id == dashboard.id
    ).all()
    destination = input.get("destination") or {"type": "file"}
    report = {
        "dashboard_id": str(dashboard.id),
        "title": dashboard.title,
        "description": dashboard.description,
        "dashboard_kind": dashboard.dashboard_kind,
        "published_version": dashboard.published_version,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "component_count": len(components),
        "components": [
            {
                "id": str(c.id),
                "title": c.title,
                "component_type": c.component_type,
                "binding_type": (c.data_binding or {}).get("type") if c.data_binding else None,
            }
            for c in components
        ],
    }
    delivery = _deliver(report, destination)
    return {
        "ok": True,
        "destination": destination,
        "report": report,
        "delivery": delivery,
        "delivered": bool(delivery.get("delivered")),
    }
