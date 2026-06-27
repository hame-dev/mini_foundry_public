"""Example workflows. Customers drop their own files alongside this one;
the registry picks them up on app startup via load_user_workflows().
"""
from app.actions.registry import workflow


@workflow("reassign_account", sync=True)
def reassign_account(session, user, params):
    """Stub: would normally update the customers.owner column. Returns the
    params it received so the audit trail captures the intent.

    Signature contract: (sync Session, User, params dict) -> dict
    """
    return {
        "ok": True,
        "action": "reassign_account",
        "user": str(user.id) if user else None,
        "params": params,
    }


@workflow("ping", sync=True)
def ping(session, user, params):
    """Smallest possible workflow — used by tests."""
    return {"pong": True, "echo": params}
