import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import sqlglot
import sqlglot.expressions as exp

from app.auth.models import GroupMember, User, UserRole
from app.auth.service import get_user_group_ids
from app.data.models import Dataset
from app.execution.sql_validator import SqlValidationError
from app.execution.sql_utils import table_key
from app.permissions.models import RowPolicy
from app.util.identifiers import quote_ident


class RowPolicyDslError(ValueError):
    pass


SUPPORTED_USER_ATTRIBUTES = {"id", "email", "name", "security_markings"}


def _literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def compile_policy_dsl(condition: dict, *, user_attributes: dict | None = None, dialect: str = "postgres") -> str:
    """Compile a small structured row-policy DSL to SQL.

    Supported nodes:
      {"op":"equals","column":"region","value":"EMEA"}
      {"op":"in","column":"region","values":["EMEA","APAC"]}
      {"op":"in_user_attribute","column":"region","attribute":"regions"}
      {"op":"and"|"or","conditions":[...]}
      {"op":"not","condition":{...}}
    """
    user_attributes = user_attributes or {}
    op = condition.get("op")
    if op in {"equals", "not_equals", "in", "in_user_attribute"}:
        column = condition.get("column")
        if not column:
            raise RowPolicyDslError("condition column is required")
        col_sql = quote_ident(str(column))
        if op == "equals":
            return f"{col_sql} = {_literal(condition.get('value'))}"
        if op == "not_equals":
            return f"{col_sql} <> {_literal(condition.get('value'))}"
        values = condition.get("values")
        if op == "in_user_attribute":
            attr = condition.get("attribute")
            values = user_attributes.get(attr, [])
        if not isinstance(values, list) or not values:
            return "FALSE"
        return f"{col_sql} IN ({', '.join(_literal(v) for v in values)})"
    if op in {"and", "or"}:
        children = condition.get("conditions") or []
        if not children:
            return "TRUE" if op == "and" else "FALSE"
        sep = " AND " if op == "and" else " OR "
        return sep.join(f"({compile_policy_dsl(c, user_attributes=user_attributes, dialect=dialect)})" for c in children)
    if op == "not":
        child = condition.get("condition")
        if not isinstance(child, dict):
            raise RowPolicyDslError("not requires condition")
        return f"NOT ({compile_policy_dsl(child, user_attributes=user_attributes, dialect=dialect)})"
    raise RowPolicyDslError(f"unsupported row policy op: {op}")


def collect_policy_references(condition: dict) -> tuple[set[str], set[str]]:
    """Return referenced dataset columns and user attributes from the policy DSL."""

    op = condition.get("op")
    columns: set[str] = set()
    attributes: set[str] = set()
    if op in {"equals", "not_equals", "in", "in_user_attribute"}:
        column = condition.get("column")
        if column:
            columns.add(str(column))
        if op == "in_user_attribute" and condition.get("attribute"):
            attributes.add(str(condition["attribute"]))
    elif op in {"and", "or"}:
        for child in condition.get("conditions") or []:
            child_cols, child_attrs = collect_policy_references(child)
            columns.update(child_cols)
            attributes.update(child_attrs)
    elif op == "not" and isinstance(condition.get("condition"), dict):
        child_cols, child_attrs = collect_policy_references(condition["condition"])
        columns.update(child_cols)
        attributes.update(child_attrs)
    return columns, attributes


def validate_policy_references(condition: dict, dataset_columns: set[str]) -> None:
    columns, attributes = collect_policy_references(condition)
    missing_columns = sorted(c for c in columns if c not in dataset_columns)
    if missing_columns:
        raise RowPolicyDslError(f"unknown dataset column(s): {', '.join(missing_columns)}")
    missing_attributes = sorted(a for a in attributes if a not in SUPPORTED_USER_ATTRIBUTES)
    if missing_attributes:
        raise RowPolicyDslError(f"unknown user attribute(s): {', '.join(missing_attributes)}")


def _compile_policy_map(
    datasets: list[Dataset],
    policies_by_dataset: dict[uuid.UUID, list[RowPolicy]],
    subjects: list[tuple[str, uuid.UUID | None]],
    user_attributes: dict | None = None,
) -> dict[str, str]:
    dataset_policies: dict[str, str] = {}
    subject_set = set(subjects)
    for ds in datasets:
        keys = {
            ds.table_name.lower(),
            f"{(getattr(ds, 'schema_name', None) or 'public').lower()}.{ds.table_name.lower()}",
        }
        all_policies = policies_by_dataset.get(ds.id, [])
        if not all_policies:
            continue
        user_policies = [p for p in all_policies if (p.subject_type, p.subject_id) in subject_set]
        if user_policies:
            conds = [
                f"({compile_policy_dsl(p.condition_json, user_attributes=user_attributes) if getattr(p, 'condition_json', None) else p.sql_condition})"
                for p in user_policies
            ]
            condition = " OR ".join(conds)
        else:
            condition = "FALSE"
        for key in keys:
            dataset_policies[key] = condition
    return dataset_policies


async def resolve_row_policies(
    session: AsyncSession,
    user_id: uuid.UUID,
    table_names: list[str],
    *,
    datasets: list[Dataset] | None = None,
) -> dict[str, str]:
    """Look up active row policies for referenced tables for a given user.

    Returns a dict mapping lowercase table_name -> SQL condition string.
    If a table has no policies defined at all, it will not be in the dictionary (no restrictions).
    If a table has policies but none apply to the user, the condition is 'FALSE'.
    """
    if not table_names and not datasets:
        return {}

    # 1. Fetch referenced datasets
    table_names_lower = [t.lower() for t in table_names]
    if datasets is None:
        datasets_q = await session.execute(
            select(Dataset).where(Dataset.table_name.in_(table_names_lower))
        )
        datasets = list(datasets_q.scalars().all())
    if not datasets:
        return {}

    # 2. Get user roles and groups (groups must be included so group-based
    # policies match the ACL subject model in permissions/enforcement.py)
    role_ids_q = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [row[0] for row in role_ids_q.all()]
    group_ids = await get_user_group_ids(session, user_id)
    subjects = (
        [("user", user_id)]
        + [("role", rid) for rid in role_ids]
        + [("group", gid) for gid in group_ids]
        + [("all_users", None)]
    )
    user = await session.get(User, user_id)
    user_attributes = {
        "id": str(user.id) if user else str(user_id),
        "email": user.email if user else "",
        "name": user.name if user and user.name else "",
        "security_markings": list(user.security_markings or []) if user else [],
    }

    policies_by_dataset: dict[uuid.UUID, list[RowPolicy]] = {}
    for ds in datasets:
        all_policies_q = await session.execute(
            select(RowPolicy).where(RowPolicy.dataset_id == ds.id)
        )
        policies_by_dataset[ds.id] = list(all_policies_q.scalars().all())

    return _compile_policy_map(datasets, policies_by_dataset, subjects, user_attributes)


async def apply_row_policies(
    session: AsyncSession, user_id: uuid.UUID, sql: str, dialect: str = "postgres"
) -> str:
    """Parse SQL, check referenced tables, lookup policies, and rewrite table references with RLS subqueries."""
    if not sql.strip():
        return sql

    try:
        statements = sqlglot.parse(sql, read=dialect)
        parsed = [s for s in statements if s is not None]
        if not parsed:
            return sql
        root = parsed[0]
    except Exception as e:
        # Fail closed: if we cannot parse the SQL we cannot prove row policies
        # were applied, so reject rather than running the query unfiltered.
        raise SqlValidationError(f"unable to apply row policies: {e}") from e

    # Extract all referenced table names
    table_names = [table.name for table in root.find_all(exp.Table)]
    if not table_names:
        return sql

    # Fetch policies for these tables
    dataset_policies = await resolve_row_policies(session, user_id, table_names)
    if not dataset_policies:
        return sql

    # Replace table nodes in AST with subqueries
    table_nodes = list(root.find_all(exp.Table))
    for table_node in table_nodes:
        table_name = table_node.name.lower()
        schema = str(table_node.db) if table_node.db else None
        key = table_key(schema, table_name)
        if key in dataset_policies or table_name in dataset_policies:
            condition = dataset_policies.get(key) or dataset_policies.get(table_name)
            if condition is None:
                continue
            alias_name = table_node.alias_or_name
            source = table_node.copy()
            source.set("alias", None)
            subquery_str = f"(SELECT * FROM {source.sql(dialect=dialect)} WHERE {condition}) AS {alias_name}"
            new_node = sqlglot.parse_one(subquery_str, read=dialect)
            table_node.replace(new_node)

    return root.sql(dialect=dialect)


def resolve_row_policies_sync(
    session: Session, user_id: uuid.UUID, table_names: list[str]
) -> dict[str, str]:
    """Look up active row policies for referenced tables for a given user synchronously."""
    if not table_names:
        return {}

    table_names_lower = [t.lower() for t in table_names]
    datasets = list(
        session.query(Dataset).filter(Dataset.table_name.in_(table_names_lower)).all()
    )
    if not datasets:
        return {}

    role_ids = [
        row[0]
        for row in session.query(UserRole.role_id)
        .filter(UserRole.user_id == user_id)
        .all()
    ]
    group_ids = [
        row[0]
        for row in session.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    ]
    subjects = (
        [("user", user_id)]
        + [("role", rid) for rid in role_ids]
        + [("group", gid) for gid in group_ids]
        + [("all_users", None)]
    )
    user = session.get(User, user_id)
    user_attributes = {
        "id": str(user.id) if user else str(user_id),
        "email": user.email if user else "",
        "name": user.name if user and user.name else "",
        "security_markings": list(user.security_markings or []) if user else [],
    }

    policies_by_dataset: dict[uuid.UUID, list[RowPolicy]] = {}
    for ds in datasets:
        policies_by_dataset[ds.id] = list(
            session.query(RowPolicy).filter(RowPolicy.dataset_id == ds.id).all()
        )
    return _compile_policy_map(datasets, policies_by_dataset, subjects, user_attributes)


def apply_row_policies_sync(
    session: Session, user_id: uuid.UUID, sql: str, dialect: str = "postgres"
) -> str:
    """Parse SQL synchronously, check referenced tables, lookup policies, and rewrite table references with RLS subqueries."""
    if not sql.strip():
        return sql

    try:
        statements = sqlglot.parse(sql, read=dialect)
        parsed = [s for s in statements if s is not None]
        if not parsed:
            return sql
        root = parsed[0]
    except Exception as e:
        # Fail closed (see apply_row_policies): reject unparseable SQL rather
        # than running it without row-policy enforcement.
        raise SqlValidationError(f"unable to apply row policies: {e}") from e

    table_names = [table.name for table in root.find_all(exp.Table)]
    if not table_names:
        return sql

    dataset_policies = resolve_row_policies_sync(session, user_id, table_names)
    if not dataset_policies:
        return sql

    table_nodes = list(root.find_all(exp.Table))
    for table_node in table_nodes:
        table_name = table_node.name.lower()
        schema = str(table_node.db) if table_node.db else None
        key = table_key(schema, table_name)
        if key in dataset_policies or table_name in dataset_policies:
            condition = dataset_policies.get(key) or dataset_policies.get(table_name)
            if condition is None:
                continue
            alias_name = table_node.alias_or_name
            source = table_node.copy()
            source.set("alias", None)
            subquery_str = f"(SELECT * FROM {source.sql(dialect=dialect)} WHERE {condition}) AS {alias_name}"
            new_node = sqlglot.parse_one(subquery_str, read=dialect)
            table_node.replace(new_node)

    return root.sql(dialect=dialect)
