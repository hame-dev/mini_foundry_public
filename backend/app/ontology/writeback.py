import uuid
from typing import Any
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.auth.models import User
from app.data.models import Dataset
from app.ontology.models import OntologyObject, OntologyAction, OntologyEdit
from app.permissions.masking import apply_masks, resolve_column_masks
from app.permissions.row_policy import resolve_row_policies
from app.util.identifiers import assert_safe_ident, quote_ident


def _branch_schema(branch_name: str) -> str:
    return f"mf_branch_{branch_name.lower().replace('-', '_')}"


async def execute_writeback(
    session: AsyncSession,
    user: User,
    action: OntologyAction,
    params: dict[str, Any]
) -> dict[str, Any]:
    if not action.object_type:
        raise ValueError("Action does not target an object type")

    # 0. Validate input against action's validation rules (before touching the DB)
    from app.ontology.validation import validate_action_input
    errors = validate_action_input(action, params)
    if errors:
        raise ValueError(f"Validation failed: {'; '.join(errors)}")

    # 1. Fetch OntologyObject mapping
    from sqlalchemy import select as sa_select
    obj_q = await session.execute(
        sa_select(OntologyObject).where(OntologyObject.type_name == action.object_type)
    )
    obj = obj_q.scalar_one_or_none()
    if obj is None:
        raise ValueError(f"Object type {action.object_type} not found in ontology")

    # 2. Fetch backing Dataset
    ds = await session.get(Dataset, obj.dataset_id)
    if ds is None:
        raise ValueError(f"Backing dataset not found for object type {action.object_type}")

    # 2a. Authorize the write against the *target dataset* itself. This is a
    # separate check from the action-resource capability (user_can_run_action):
    # holding `run`/`writeback` on the action does not by itself authorize
    # mutating the backing dataset. Require `writeback` (or `edit`) on the
    # dataset resource. Owners/admins short-circuit inside enforcement.
    from app.permissions.enforcement import (
        effective_capabilities_for_object,
        PermissionDenied,
    )

    target_caps = await effective_capabilities_for_object(session, user, "dataset", ds.id)
    if not ({"writeback", "edit", "manage"} & target_caps):
        raise PermissionDenied(
            f"missing capability: writeback on dataset backing {action.object_type}"
        )

    # 3. Determine explicit change type
    change_type = (action.change_type or "update").lower()
    if change_type not in {"create", "update", "delete"}:
        raise ValueError(f"Unsupported action change_type: {action.change_type}")

    # Validate names are safe
    branch_name = str(params.get("_branch_name") or params.get("branch_name") or getattr(ds, "branch_name", None) or "main")
    schema_name = _branch_schema(branch_name) if branch_name != "main" else ds.schema_name

    assert_safe_ident(schema_name)
    assert_safe_ident(ds.table_name)
    assert_safe_ident(obj.primary_key)

    qualified_table = f"{quote_ident(schema_name)}.{quote_ident(ds.table_name)}"
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)

    pk_col = obj.primary_key
    properties = obj.properties or []
    
    # Map property name (frontend key) to physical column name
    prop_to_col = {}
    for p in properties:
        name = p.get("name") or p.get("column")
        col = p.get("column", name)
        prop_to_col[name] = col

    # Check for direct primary key matching parameter or property matching primary key column
    pk_val = params.get(pk_col) or params.get("id")
    
    policy_conditions = await resolve_row_policies(session, user.id, [ds.table_name], datasets=[ds])
    policy_condition = (
        policy_conditions.get(f"{(ds.schema_name or 'public').lower()}.{ds.table_name.lower()}")
        or policy_conditions.get(ds.table_name.lower())
    )
    policy_sql = f" AND ({policy_condition})" if policy_condition else ""
    masks = await resolve_column_masks(session, user.id, ds.id)

    # Block writes to columns the caller cannot see in full (hidden/null/hash/
    # partial masks). A user who is not authorized to read the true value of a
    # column must not be able to overwrite it. Applies to create/update only;
    # delete operates on the whole row and is already row-policy gated.
    if change_type in {"create", "update"} and masks:
        for k in params:
            if str(k).startswith("_"):
                continue  # control params like _branch_name
            col_name = prop_to_col.get(k) or k
            if col_name in masks:
                raise ValueError(
                    f"cannot write to masked/unauthorized column: {col_name}"
                )

    old_row = None
    new_row = None

    with engine.begin() as conn:
        if change_type == "create":
            # Formulate insert columns and values
            insert_cols = []
            insert_params = {}
            
            # If primary key is not provided and is a uuid type, generate it
            if not pk_val:
                pk_val = str(uuid.uuid4())
                
            insert_cols.append(quote_ident(pk_col))
            insert_params[pk_col] = pk_val

            for k, v in params.items():
                col_name = prop_to_col.get(k) or k
                if col_name != pk_col and col_name in [p.get("column") for p in properties]:
                    assert_safe_ident(col_name)
                    insert_cols.append(quote_ident(col_name))
                    insert_params[col_name] = v

            col_str = ", ".join(insert_cols)
            val_placeholders = ", ".join([f":{c}" for c in insert_params.keys()])
            insert_sql = f"INSERT INTO {qualified_table} ({col_str}) VALUES ({val_placeholders})"
            
            conn.execute(text(insert_sql), insert_params)
            
            # Fetch the newly created row
            select_sql = f"SELECT * FROM {qualified_table} WHERE {quote_ident(pk_col)} = :pk{policy_sql}"
            res = conn.execute(text(select_sql), {"pk": pk_val}).mappings().first()
            if res is None:
                raise ValueError("Created row is outside the caller's row policy")
            if res:
                new_row = dict(res)

        elif change_type == "update":
            if not pk_val:
                raise ValueError(f"Primary key {pk_col} value required for update operations")

            # Fetch old row
            select_sql = f"SELECT * FROM {qualified_table} WHERE {quote_ident(pk_col)} = :pk{policy_sql}"
            res = conn.execute(text(select_sql), {"pk": pk_val}).mappings().first()
            if not res:
                raise ValueError(f"Record with {pk_col}={pk_val} not found")
            old_row = dict(res)

            # Formulate update SET statements
            set_clauses = []
            update_params = {"pk_val": pk_val}
            for k, v in params.items():
                col_name = prop_to_col.get(k) or k
                if col_name != pk_col and col_name in [p.get("column") for p in properties]:
                    assert_safe_ident(col_name)
                    set_clauses.append(f"{quote_ident(col_name)} = :{col_name}")
                    update_params[col_name] = v

            if set_clauses:
                update_sql = f"UPDATE {qualified_table} SET {', '.join(set_clauses)} WHERE {quote_ident(pk_col)} = :pk_val{policy_sql}"
                conn.execute(text(update_sql), update_params)
                
                # Fetch updated row
                res_updated = conn.execute(text(select_sql), {"pk": pk_val}).mappings().first()
                if res_updated:
                    new_row = dict(res_updated)
            else:
                new_row = old_row

        elif change_type == "delete":
            if not pk_val:
                raise ValueError(f"Primary key {pk_col} value required for delete operations")

            # Fetch old row before delete
            select_sql = f"SELECT * FROM {qualified_table} WHERE {quote_ident(pk_col)} = :pk{policy_sql}"
            res = conn.execute(text(select_sql), {"pk": pk_val}).mappings().first()
            if not res:
                raise ValueError(f"Record with {pk_col}={pk_val} not found")
            old_row = dict(res)

            delete_sql = f"DELETE FROM {qualified_table} WHERE {quote_ident(pk_col)} = :pk{policy_sql}"
            conn.execute(text(delete_sql), {"pk": pk_val})

    masked_old = apply_masks([old_row], masks)[0] if old_row is not None else None
    masked_new = apply_masks([new_row], masks)[0] if new_row is not None else None

    # 4. Log OntologyEdit audit row
    edit = OntologyEdit(
        user_id=user.id,
        object_type=action.object_type,
        object_key=str(pk_val),
        change_type=change_type,
        old_values=masked_old,
        new_values=masked_new,
        status="applied"
    )
    session.add(edit)
    await session.flush()

    # 5. Enqueue webhook notification if configured
    if action.webhook_url:
        try:
            from app.jobs.tasks.ontology_webhook import dispatch_ontology_webhook
            dispatch_ontology_webhook.delay(
                webhook_url=action.webhook_url,
                webhook_secret=action.webhook_secret,
                payload={
                    "action_key": action.workflow_key,
                    "object_type": action.object_type,
                    "pk": str(pk_val),
                    "change_type": change_type,
                    "old_values": masked_old,
                    "new_values": masked_new,
                    "triggered_by": str(user.id),
                    "branch_name": branch_name,
                },
            )
        except Exception:
            pass  # webhook errors never block the write

    return {
        "status": "success",
        "change_type": change_type,
        "object_key": str(pk_val),
        "old_values": masked_old,
        "new_values": masked_new,
        "branch_name": branch_name,
    }
