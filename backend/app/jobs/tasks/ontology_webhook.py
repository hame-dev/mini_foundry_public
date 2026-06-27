"""Celery task: dispatch POST webhook after an ontology writeback.

Signs the body with HMAC-SHA256 if a webhook_secret is provided.
Retries 3 times with exponential backoff on any network error.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

from app.jobs.celery_app import celery_app


@celery_app.task(
    name="ontology_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def dispatch_ontology_webhook(
    self,
    webhook_url: str,
    webhook_secret: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    import urllib.request
    import urllib.error

    payload["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
    body = json.dumps(payload, default=str).encode()

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MiniFoundry-Webhook/1.0",
    }

    if webhook_secret:
        sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-MiniFoundry-Signature"] = f"sha256={sig}"

    req = urllib.request.Request(webhook_url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        if status_code >= 500:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 5)

    return {"delivered": True, "status_code": status_code, "url": webhook_url}
