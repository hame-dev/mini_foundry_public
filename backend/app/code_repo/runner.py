import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.models import Dataset, DatasetColumn
from app.code_repo.transforms import registry
from app.util.identifiers import assert_safe_ident


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_files(tmp: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        dest = os.path.join(tmp, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True) if os.sep in name else None
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)


def _app_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _venv_python(venv_dir: str) -> str:
    return os.path.join(venv_dir, "bin", "python")


def _requirements_hash(requirements: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(requirements)).encode()).hexdigest()[:16]


def _ensure_venv(requirements: list[str]) -> str | None:
    """Create or reuse a cached virtualenv for the given requirements list.

    Returns the path to the venv directory, or None if no requirements.
    """
    if not requirements:
        return None

    cache_base = Path(tempfile.gettempdir()) / "mini_foundry_venvs"
    cache_base.mkdir(exist_ok=True)
    key = _requirements_hash(requirements)
    venv_dir = str(cache_base / key)

    if not os.path.exists(venv_dir):
        venv.create(venv_dir, with_pip=True, clear=True)
        python = _venv_python(venv_dir)
        subprocess.run(
            [python, "-m", "pip", "install", "--quiet", *requirements],
            check=True,
            capture_output=True,
        )

    return venv_dir


# ---------------------------------------------------------------------------
# Multi-file transform execution
# ---------------------------------------------------------------------------

def _resolve_main_file(files: dict[str, str]) -> str | None:
    """Pick the entry module: transforms.py, else the first non-test .py file."""
    if "transforms.py" in files:
        return "transforms.py"
    return next(
        (
            n
            for n in files
            if n.endswith(".py") and not (n.startswith("test_") or n.endswith("_test.py"))
        ),
        None,
    )


async def run_code_transform(
    session: AsyncSession,
    user_id: Any,
    files: dict[str, str],
    requirements: list[str] | None = None,
) -> dict[str, Any]:
    """Execute user @transform files, isolated in a Docker sandbox when available.

    The sandbox path never runs user code on the host: a "discover" pass learns
    each transform's declared inputs/outputs, the host provisions those inputs
    (RLS + masking) as read-only parquet plus an ontology snapshot, then an
    "execute" pass runs the transforms. Outputs are read back and persisted to
    Postgres. Falls back to in-process execution when Docker is unreachable or
    when extra `requirements` are needed (which cannot be installed under
    --network=none).
    """
    from app.notebooks.sandbox import docker_available

    requirements = requirements or []
    use_sandbox = docker_available() and not requirements
    if use_sandbox:
        try:
            return await _run_code_transform_sandbox(session, user_id, files)
        except _SandboxUnavailable:
            pass  # fall through to host execution only if explicitly allowed
    if not get_settings().allow_inprocess_code_exec:
        raise ValueError(
            "code execution sandbox unavailable (Docker required); "
            "in-process execution is disabled"
        )
    return await _run_code_transform_inprocess(session, user_id, files, requirements)


class _SandboxUnavailable(Exception):
    """Raised when the sandbox cannot run (so the caller falls back to host)."""


async def _read_input_dataset_df(
    session: AsyncSession, user_id: Any, ds: "Dataset"
) -> pd.DataFrame:
    """Read a dataset to a DataFrame with RLS + column masking applied."""
    assert_safe_ident(ds.schema_name)
    assert_safe_ident(ds.table_name)
    sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
    from app.permissions.row_policy import apply_row_policies
    rewritten_sql = await apply_row_policies(session, user_id, sql)

    engine = create_engine(get_settings().sync_database_url)
    df = pd.read_sql_query(rewritten_sql, engine)

    from app.permissions.masking import resolve_column_masks, apply_masks_to_df
    masks = await resolve_column_masks(session, user_id, ds.id)
    return apply_masks_to_df(df, masks)


async def _build_ontology_snapshot(
    session: AsyncSession, dataset_ids: list[Any]
) -> dict[str, Any]:
    """Async ontology snapshot for the given backing datasets (see
    app.notebooks.execution.build_ontology_snapshot for the shape)."""
    if not dataset_ids:
        return {"object_types": [], "relationships": []}
    from app.ontology.models import OntologyObject, OntologyRelationship

    object_types: list[dict[str, Any]] = []
    type_names: set[str] = set()
    objs = (await session.execute(
        select(OntologyObject).where(OntologyObject.dataset_id.in_(dataset_ids))
    )).scalars().all()
    for obj in objs:
        ds = await session.get(Dataset, obj.dataset_id)
        if ds is None:
            continue
        object_types.append({
            "type_name": obj.type_name,
            "primary_key": obj.primary_key,
            "display_name_column": obj.display_name_column,
            "dataset_name": ds.name,
            "properties": obj.properties,
            "description": obj.description,
        })
        type_names.add(obj.type_name)

    relationships: list[dict[str, Any]] = []
    if type_names:
        rels = (await session.execute(
            select(OntologyRelationship).where(
                OntologyRelationship.source_type.in_(type_names)
            )
        )).scalars().all()
        relationships = [{
            "source_type": r.source_type, "target_type": r.target_type,
            "name": r.name, "cardinality": r.cardinality,
            "source_key": r.source_key, "target_key": r.target_key,
        } for r in rels]
    return {"object_types": object_types, "relationships": relationships}


async def _persist_transform_output(
    session: AsyncSession,
    user_id: Any,
    out_name: str,
    output_df: pd.DataFrame,
    markings: list[str],
) -> dict[str, Any]:
    """Write a transform's output DataFrame to Postgres and upsert its Dataset."""
    out_ds = (await session.execute(
        select(Dataset).where(Dataset.name == out_name)
    )).scalar_one_or_none()

    out_table = f"mf_py_{out_name.lower().replace(' ', '_')}"
    assert_safe_ident(out_table)
    out_schema = "public"

    engine = create_engine(get_settings().sync_database_url)
    output_df.to_sql(out_table, engine, schema=out_schema, if_exists="replace", index=False)

    if out_ds is None:
        out_ds = Dataset(
            name=out_name,
            description="Generated via sandboxed code transform",
            schema_name=out_schema,
            table_name=out_table,
            execution_engine="python",
            row_count=len(output_df),
            security_markings=markings,
            owner_id=user_id,
        )
        session.add(out_ds)
        await session.flush()
    else:
        out_ds.schema_name = out_schema
        out_ds.table_name = out_table
        out_ds.row_count = len(output_df)
        out_ds.security_markings = markings

    from sqlalchemy import delete
    await session.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == out_ds.id))
    for col_name in output_df.columns:
        session.add(DatasetColumn(
            dataset_id=out_ds.id, name=str(col_name),
            data_type=str(output_df[col_name].dtype),
        ))
    return {
        "output_dataset_name": out_name,
        "output_table": f"{out_schema}.{out_table}",
        "row_count": len(output_df),
        "columns": [str(c) for c in output_df.columns],
    }


async def _run_code_transform_sandbox(
    session: AsyncSession, user_id: Any, files: dict[str, str]
) -> dict[str, Any]:
    """Docker-isolated transform execution (two-phase: discover then execute)."""
    from app.notebooks.sandbox import run_transform, safe_output_stem

    main_file = _resolve_main_file(files)
    if main_file is None:
        raise ValueError("No Python source file found to execute.")

    # Phase 1 — discover declared inputs/outputs without running user code.
    discovered = run_transform(files, main_file, mode="discover")
    # "declared" is absent only when the container itself failed to run (e.g.
    # the sandbox image isn't built) — fall back to the host path in that case.
    if "declared" not in discovered:
        raise _SandboxUnavailable(discovered.get("error") or "sandbox did not run")
    if discovered.get("error"):
        raise ValueError(f"Failed to load transforms: {discovered['error']}")
    declared = discovered.get("declared") or []
    if not declared:
        raise ValueError("No @transform-decorated functions found. Did you use @transform?")

    # Resolve every declared input dataset, applying RLS + masking, to parquet.
    parquet_dir = Path(tempfile.mkdtemp(prefix="mf_tx_inputs_"))
    permitted: dict[str, str] = {}
    name_to_dataset: dict[str, "Dataset"] = {}
    for spec in declared:
        for ds_name in spec.get("inputs", {}).values():
            if ds_name in permitted:
                continue
            ds = (await session.execute(
                select(Dataset).where(Dataset.name == ds_name)
            )).scalar_one_or_none()
            if ds is None:
                raise ValueError(f"Input dataset '{ds_name}' not found")
            df = await _read_input_dataset_df(session, user_id, ds)
            target = parquet_dir / f"{ds.id.hex}.parquet"
            df.to_parquet(target, index=False)
            permitted[ds_name] = str(target)
            name_to_dataset[ds_name] = ds

    ontology = await _build_ontology_snapshot(
        session, [ds.id for ds in name_to_dataset.values()]
    )

    try:
        # Phase 2 — execute the transforms with inputs + ontology mounted.
        executed = run_transform(
            files, main_file, mode="execute",
            permitted_datasets=permitted, ontology_snapshot=ontology,
        )
    finally:
        shutil.rmtree(parquet_dir, ignore_errors=True)

    if "transforms" not in executed:
        # Container failed to run at all — fall back to the host path.
        raise _SandboxUnavailable(executed.get("error") or "sandbox did not run")
    if executed.get("error"):
        raise ValueError(executed["error"])

    saved: dict[str, str] = executed.get("saved_dataframes") or {}
    if not saved:
        raise ValueError("transforms produced no output datasets")

    results = []
    saved_temp_dirs: set[str] = set()
    for spec in declared:
        out_name = spec["output"]
        stem = safe_output_stem(out_name)
        path = saved.get(stem)
        if path is None:
            continue
        saved_temp_dirs.add(str(Path(path).parent))
        output_df = pd.read_parquet(path)
        # Inherit markings from this transform's input datasets.
        markings: set[str] = set()
        for ds_name in spec.get("inputs", {}).values():
            ds = name_to_dataset.get(ds_name)
            if ds is not None:
                markings.update(ds.security_markings or [])
        results.append(
            await _persist_transform_output(
                session, user_id, out_name, output_df, list(markings)
            )
        )

    await session.commit()
    for d in saved_temp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    return {"status": "success", "transforms": results, "isolation": "docker"}


async def _run_code_transform_inprocess(
    session: AsyncSession,
    user_id: Any,
    files: dict[str, str],
    requirements: list[str] | None = None,
) -> dict[str, Any]:
    """Execute user-defined Python files containing @transform decorators.

    All files are written to a temp directory so that inter-file imports work.
    """
    # 1. Reset registry
    registry.transforms = []

    requirements = requirements or []
    tmp = tempfile.mkdtemp(prefix="mf_code_")
    try:
        _write_files(tmp, files)

        # 2. Optionally set up venv (best-effort; falls back to sys path)
        venv_dir = None
        try:
            venv_dir = _ensure_venv(requirements)
        except Exception:
            pass  # non-fatal — continue without extra packages

        # 3. Build namespace and exec the main transform file
        main_file = _resolve_main_file(files)
        if main_file is None:
            raise ValueError("No Python source file found to execute.")

        # Add tmp dir to sys.path so intra-repo imports work
        if tmp not in sys.path:
            sys.path.insert(0, tmp)

        # If venv is set, prepend its site-packages to sys.path
        if venv_dir:
            import site
            venv_site = os.path.join(
                venv_dir,
                "lib",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                "site-packages",
            )
            if os.path.isdir(venv_site) and venv_site not in sys.path:
                sys.path.insert(0, venv_site)

        namespace = {
            "transform": sys.modules["app.code_repo.transforms"].transform,
            "Input": sys.modules["app.code_repo.transforms"].Input,
            "Output": sys.modules["app.code_repo.transforms"].Output,
        }

        main_path = os.path.join(tmp, main_file)
        with open(main_path, "r", encoding="utf-8") as f:
            code = f.read()

        try:
            exec(compile(code, main_path, "exec"), namespace)
        except Exception as e:
            raise ValueError(f"Failed to execute '{main_file}': {e}")

        if not registry.transforms:
            raise ValueError(
                "No @transform-decorated functions found. Did you use @transform?"
            )

        settings = get_settings()
        engine = create_engine(settings.sync_database_url)
        results = []

        for tx in registry.transforms:
            inputs = tx["inputs"]
            output = tx["output"]
            fn = tx["fn"]

            # Resolve inputs to DataFrames
            input_dfs: dict[str, pd.DataFrame] = {}
            inherited_markings = set()
            for param_name, inp in inputs.items():
                ds_q = await session.execute(
                    select(Dataset).where(Dataset.name == inp.dataset_name)
                )
                ds = ds_q.scalar_one_or_none()
                if ds is None:
                    raise ValueError(f"Input dataset '{inp.dataset_name}' not found")

                assert_safe_ident(ds.schema_name)
                assert_safe_ident(ds.table_name)
                inherited_markings.update(ds.security_markings or [])

                # RLS
                sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
                from app.permissions.row_policy import apply_row_policies
                rewritten_sql = await apply_row_policies(session, user_id, sql)

                df = pd.read_sql_query(rewritten_sql, engine)

                # Column masking
                from app.permissions.masking import resolve_column_masks, apply_masks_to_df
                masks = await resolve_column_masks(session, user_id, ds.id)
                df = apply_masks_to_df(df, masks)

                input_dfs[param_name] = df

            # Execute transform
            try:
                output_df = fn(**input_dfs)
            except Exception as e:
                raise ValueError(
                    f"Exception inside transform '{fn.__name__}': {e}"
                )

            if not isinstance(output_df, pd.DataFrame):
                raise ValueError(
                    f"Transform '{fn.__name__}' must return a pandas DataFrame, "
                    f"got {type(output_df)}"
                )

            # Persist output dataset
            out_name = output.dataset_name
            out_ds_q = await session.execute(
                select(Dataset).where(Dataset.name == out_name)
            )
            out_ds = out_ds_q.scalar_one_or_none()

            out_table = f"mf_py_{out_name.lower().replace(' ', '_')}"
            assert_safe_ident(out_table)
            out_schema = "public"

            output_df.to_sql(
                out_table, engine, schema=out_schema, if_exists="replace", index=False
            )

            markings_list = list(inherited_markings)
            if out_ds is None:
                out_ds = Dataset(
                    name=out_name,
                    description=f"Generated via code transform '{fn.__name__}'",
                    schema_name=out_schema,
                    table_name=out_table,
                    execution_engine="python",
                    row_count=len(output_df),
                    security_markings=markings_list,
                    owner_id=user_id,
                )
                session.add(out_ds)
                await session.flush()
            else:
                out_ds.schema_name = out_schema
                out_ds.table_name = out_table
                out_ds.row_count = len(output_df)
                out_ds.security_markings = markings_list

            from sqlalchemy import delete
            await session.execute(
                delete(DatasetColumn).where(DatasetColumn.dataset_id == out_ds.id)
            )
            for col_name in output_df.columns:
                session.add(
                    DatasetColumn(
                        dataset_id=out_ds.id,
                        name=col_name,
                        data_type=str(output_df[col_name].dtype),
                    )
                )

            results.append(
                {
                    "output_dataset_name": out_name,
                    "output_table": f"{out_schema}.{out_table}",
                    "row_count": len(output_df),
                    "columns": list(output_df.columns),
                }
            )

        await session.commit()
        return {"status": "success", "transforms": results, "isolation": "host"}

    finally:
        try:
            sys.path.remove(tmp)
        except ValueError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Sync, sandbox-only orchestration (worker job path)
# ---------------------------------------------------------------------------

def _read_input_dataset_df_sync(session: Session, user_id: Any, ds: "Dataset") -> pd.DataFrame:
    assert_safe_ident(ds.schema_name)
    assert_safe_ident(ds.table_name)
    sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
    from app.permissions.row_policy import apply_row_policies_sync
    rewritten_sql = apply_row_policies_sync(session, user_id, sql)
    engine = create_engine(get_settings().sync_database_url)
    df = pd.read_sql_query(rewritten_sql, engine)
    from app.permissions.masking import resolve_column_masks_sync, apply_masks_to_df
    masks = resolve_column_masks_sync(session, user_id, ds.id)
    return apply_masks_to_df(df, masks)


def _build_ontology_snapshot_sync(session: Session, dataset_ids: list[Any]) -> dict[str, Any]:
    if not dataset_ids:
        return {"object_types": [], "relationships": []}
    from app.ontology.models import OntologyObject, OntologyRelationship

    object_types: list[dict[str, Any]] = []
    type_names: set[str] = set()
    objs = session.execute(
        select(OntologyObject).where(OntologyObject.dataset_id.in_(dataset_ids))
    ).scalars().all()
    for obj in objs:
        ds = session.get(Dataset, obj.dataset_id)
        if ds is None:
            continue
        object_types.append({
            "type_name": obj.type_name, "primary_key": obj.primary_key,
            "display_name_column": obj.display_name_column, "dataset_name": ds.name,
            "properties": obj.properties, "description": obj.description,
        })
        type_names.add(obj.type_name)
    relationships: list[dict[str, Any]] = []
    if type_names:
        rels = session.execute(
            select(OntologyRelationship).where(OntologyRelationship.source_type.in_(type_names))
        ).scalars().all()
        relationships = [{
            "source_type": r.source_type, "target_type": r.target_type,
            "name": r.name, "cardinality": r.cardinality,
            "source_key": r.source_key, "target_key": r.target_key,
        } for r in rels]
    return {"object_types": object_types, "relationships": relationships}


def _persist_transform_output_sync(
    session: Session, user_id: Any, out_name: str, output_df: pd.DataFrame, markings: list[str]
) -> dict[str, Any]:
    out_ds = session.execute(select(Dataset).where(Dataset.name == out_name)).scalar_one_or_none()
    out_table = f"mf_py_{out_name.lower().replace(' ', '_')}"
    assert_safe_ident(out_table)
    out_schema = "public"
    engine = create_engine(get_settings().sync_database_url)
    output_df.to_sql(out_table, engine, schema=out_schema, if_exists="replace", index=False)
    if out_ds is None:
        out_ds = Dataset(
            name=out_name, description="Generated via sandboxed code transform",
            schema_name=out_schema, table_name=out_table, execution_engine="python",
            row_count=len(output_df), security_markings=markings, owner_id=user_id,
        )
        session.add(out_ds)
        session.flush()
    else:
        out_ds.schema_name = out_schema
        out_ds.table_name = out_table
        out_ds.row_count = len(output_df)
        out_ds.security_markings = markings
    session.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == out_ds.id))
    for col_name in output_df.columns:
        session.add(DatasetColumn(dataset_id=out_ds.id, name=str(col_name), data_type=str(output_df[col_name].dtype)))
    return {
        "output_dataset_name": out_name,
        "output_table": f"{out_schema}.{out_table}",
        "row_count": len(output_df),
        "columns": [str(c) for c in output_df.columns],
    }


def run_code_transform_sync(
    session: Session, user_id: Any, files: dict[str, str], requirements: list[str] | None = None,
) -> dict[str, Any]:
    """Sandbox-only @transform execution for the worker. Fails closed: never
    runs user code in this process."""
    from app.notebooks.sandbox import docker_available, run_transform, safe_output_stem

    requirements = requirements or []
    if requirements:
        raise ValueError("custom pip requirements are not supported in the sandbox")
    if not docker_available():
        raise ValueError("code execution sandbox unavailable (Docker required)")

    main_file = _resolve_main_file(files)
    if main_file is None:
        raise ValueError("No Python source file found to execute.")

    discovered = run_transform(files, main_file, mode="discover")
    if "declared" not in discovered:
        raise ValueError(discovered.get("error") or "sandbox did not run")
    if discovered.get("error"):
        raise ValueError(f"Failed to load transforms: {discovered['error']}")
    declared = discovered.get("declared") or []
    if not declared:
        raise ValueError("No @transform-decorated functions found. Did you use @transform?")

    parquet_dir = Path(tempfile.mkdtemp(prefix="mf_tx_inputs_"))
    permitted: dict[str, str] = {}
    name_to_dataset: dict[str, "Dataset"] = {}
    try:
        for spec in declared:
            for ds_name in spec.get("inputs", {}).values():
                if ds_name in permitted:
                    continue
                ds = session.execute(select(Dataset).where(Dataset.name == ds_name)).scalar_one_or_none()
                if ds is None:
                    raise ValueError(f"Input dataset '{ds_name}' not found")
                df = _read_input_dataset_df_sync(session, user_id, ds)
                target = parquet_dir / f"{ds.id.hex}.parquet"
                df.to_parquet(target, index=False)
                permitted[ds_name] = str(target)
                name_to_dataset[ds_name] = ds

        ontology = _build_ontology_snapshot_sync(session, [ds.id for ds in name_to_dataset.values()])
        executed = run_transform(
            files, main_file, mode="execute",
            permitted_datasets=permitted, ontology_snapshot=ontology,
        )
    finally:
        shutil.rmtree(parquet_dir, ignore_errors=True)

    if "transforms" not in executed:
        raise ValueError(executed.get("error") or "sandbox did not run")
    if executed.get("error"):
        raise ValueError(executed["error"])
    saved: dict[str, str] = executed.get("saved_dataframes") or {}
    if not saved:
        raise ValueError("transforms produced no output datasets")

    results = []
    saved_temp_dirs: set[str] = set()
    for spec in declared:
        out_name = spec["output"]
        path = saved.get(safe_output_stem(out_name))
        if path is None:
            continue
        saved_temp_dirs.add(str(Path(path).parent))
        output_df = pd.read_parquet(path)
        markings: set[str] = set()
        for ds_name in spec.get("inputs", {}).values():
            ds = name_to_dataset.get(ds_name)
            if ds is not None:
                markings.update(ds.security_markings or [])
        results.append(_persist_transform_output_sync(session, user_id, out_name, output_df, list(markings)))

    session.commit()
    for d in saved_temp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    return {"status": "success", "transforms": results, "isolation": "docker"}


def run_code_tests_sync(files: dict[str, str], test_file: str) -> list[dict[str, Any]]:
    """Sandbox-only pytest execution for the worker. Fails closed."""
    from app.notebooks.sandbox import docker_available, run_tests

    if not docker_available():
        raise ValueError("code execution sandbox unavailable (Docker required)")
    result = run_tests(files, test_file)
    if result.get("error"):
        return [{"name": "runner", "status": "error", "message": str(result["error"])[:500]}]
    return result.get("results") or []


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_code_tests(
    files: dict[str, str],
    test_file: str,
) -> list[dict[str, Any]]:
    """Run pytest on *test_file* inside a temp directory.

    Returns a list of per-test result dicts:
        {"name": str, "status": "passed"|"failed"|"error", "message": str|None}

    Host execution path: only reachable when ``allow_inprocess_code_exec`` is
    explicitly enabled (local dev / tests). Production uses ``run_code_tests_sync``
    (sandbox) via the worker.
    """
    if not get_settings().allow_inprocess_code_exec:
        raise ValueError("host test execution is disabled; use the sandbox")
    tmp = tempfile.mkdtemp(prefix="mf_test_")
    try:
        _write_files(tmp, files)
        _write_test_bootstrap(tmp, files)

        report_path = os.path.join(tmp, ".report.json")

        # pytest-json-report writes a JSON file we can parse
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [tmp, _app_root(), env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                test_file,
                "--json-report",
                f"--json-report-file={report_path}",
                "--tb=short",
                "-q",
            ],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            return _parse_pytest_report(report)

        # Fallback: pytest-json-report not installed — parse plain text output
        return _parse_plain_pytest_output(result.stdout + result.stderr)

    except subprocess.TimeoutExpired:
        return [{"name": "timeout", "status": "error", "message": "Test run exceeded 60s timeout"}]
    except Exception as e:
        return [{"name": "runner", "status": "error", "message": str(e)}]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_test_bootstrap(tmp: str, files: dict[str, str]) -> None:
    """Provide SDK symbols and a default transformed_df fixture for repo tests."""
    if "conftest.py" in files:
        return

    source_files = [
        name
        for name in files
        if name.endswith(".py") and not (name.startswith("test_") or name.endswith("_test.py"))
    ]
    main_file = "transforms.py" if "transforms.py" in files else (source_files[0] if source_files else "")
    bootstrap = f'''
import builtins
import importlib
import sys

import pandas as pd
import pytest

from app.code_repo.transforms import Input, Output, registry, transform

builtins.Input = Input
builtins.Output = Output
builtins.transform = transform


def _sample_frame():
    return pd.DataFrame({{
        "customer_id": [1, 2, 3],
        "name": ["Acme", "Beacon", "Cobalt"],
        "segment": ["enterprise", "mid-market", "enterprise"],
        "ltv": [1500, 250, 2200],
        "amount": [1500.0, 250.0, 2200.0],
        "status": ["active", "trial", "active"],
    }})


@pytest.fixture
def transformed_df():
    registry.transforms = []
    main_file = {main_file!r}
    if not main_file:
        raise RuntimeError("No Python source file found to test.")

    module_name = main_file[:-3].replace("/", ".")
    sys.modules.pop(module_name, None)
    importlib.import_module(module_name)

    if not registry.transforms:
        raise RuntimeError("No @transform-decorated functions found.")

    tx = registry.transforms[0]
    inputs = {{name: _sample_frame().copy() for name in tx["inputs"]}}
    return tx["fn"](**inputs)
'''
    Path(tmp, "conftest.py").write_text(bootstrap.lstrip(), encoding="utf-8")


def _parse_pytest_report(report: dict) -> list[dict[str, Any]]:
    results = []
    for test in report.get("tests", []):
        node_id = test.get("nodeid", "unknown")
        outcome = test.get("outcome", "error")
        status = "passed" if outcome == "passed" else ("failed" if outcome == "failed" else "error")
        message: str | None = None
        if outcome != "passed":
            call = test.get("call") or {}
            longrepr = call.get("longrepr") or test.get("longrepr")
            if longrepr:
                message = str(longrepr)[:500]
        results.append({"name": node_id, "status": status, "message": message})
    return results


def _parse_plain_pytest_output(output: str) -> list[dict[str, Any]]:
    """Minimal parser for plain pytest -q output when json-report is absent."""
    results = []
    for line in output.splitlines():
        if " PASSED" in line:
            name = line.split(" PASSED")[0].strip()
            results.append({"name": name, "status": "passed", "message": None})
        elif " FAILED" in line:
            name = line.split(" FAILED")[0].strip()
            results.append({"name": name, "status": "failed", "message": None})
        elif " ERROR" in line:
            name = line.split(" ERROR")[0].strip()
            results.append({"name": name, "status": "error", "message": None})
    if not results:
        results.append({"name": "unknown", "status": "error", "message": output[:500]})
    return results
