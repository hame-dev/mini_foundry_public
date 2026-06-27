"""Host-side wrapper that runs a user's Python cell inside a sandboxed
container. See README §8 and the v0.5 plan section.

The worker that calls this MUST have access to the Docker daemon socket;
the spawned sandbox container itself does NOT (it runs with --network=none).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any

SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "mini-foundry-sandbox:0.5")
SANDBOX_WORK_ROOT = Path(os.getenv("SANDBOX_WORK_ROOT", tempfile.gettempdir())).resolve()
SANDBOX_DOCKER_MOUNT_ROOT = os.getenv("SANDBOX_DOCKER_MOUNT_ROOT")


def _settings():
    from app.config import get_settings

    return get_settings()


def sandbox_image() -> str:
    return os.getenv("SANDBOX_IMAGE") or _settings().sandbox_image


def sandbox_docker_host() -> str:
    """Daemon the sandbox should talk to. Empty = inherit (host socket)."""
    return os.getenv("SANDBOX_DOCKER_HOST") or _settings().sandbox_docker_host


def sandbox_runtime() -> str:
    """Optional hardened OCI runtime (e.g. 'runsc'). Empty = daemon default."""
    return os.getenv("SANDBOX_RUNTIME") or _settings().sandbox_runtime


def _docker_env() -> dict[str, str] | None:
    """Subprocess env for docker calls; points at the isolated daemon when set.

    Returns None to inherit the process environment (default host socket).
    """
    host = sandbox_docker_host()
    if not host:
        return None
    env = os.environ.copy()
    env["DOCKER_HOST"] = host
    return env


def validate_requirements_allowlist(requirements: list[str] | None) -> None:
    allowed = {item.strip().lower() for item in _settings().sandbox_allowed_packages.split(",") if item.strip()}
    for requirement in requirements or []:
        name = requirement.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].split("[", 1)[0].strip().lower()
        if name not in allowed:
            raise ValueError(f"package {name!r} is not allowed in sandbox requirements")


def _directory_size_bytes(path: Path) -> int:
    return sum(file_path.stat().st_size for file_path in path.rglob("*") if file_path.is_file())


WRAPPER_TEMPLATE = textwrap.dedent('''
    import base64, io, json, os, sys, traceback
    from pathlib import Path

    sys.path.insert(0, "/opt/sdk")
    import platform_sdk  # auto-configures from MF_CTX
    import platform_sdk.objects as _objects

    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = stdout_buf, stderr_buf

    user_globals = {{
        "platform_sdk": platform_sdk,
        "load_table": platform_sdk.load_table,
        "query": platform_sdk.query,
        "objects": _objects,
    }}

    err = None
    try:
        exec(compile({user_code!r}, "<cell>", "exec"), user_globals)
    except Exception as e:  # noqa: BLE001
        err = f"{{type(e).__name__}}: {{e}}\\n" + traceback.format_exc()

    # Snapshot matplotlib figures
    images_b64 = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        for fignum in plt.get_fignums():
            fig = plt.figure(fignum)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight")
            images_b64.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    except Exception:
        pass

    # Snapshot any user-created pandas DataFrames (small samples only)
    dataframes = []
    try:
        import pandas as pd
        for k, v in list(user_globals.items()):
            if isinstance(v, pd.DataFrame):
                sample = v.head(50)
                dataframes.append({{
                    "name": k,
                    "columns": list(sample.columns.astype(str)),
                    "rows": [
                        {{c: (None if pd.isna(r[c]) else r[c]) for c in sample.columns}}
                        for _, r in sample.iterrows()
                    ],
                    "total_rows": int(len(v)),
                }})
    except Exception:
        pass

    Path("/workspace/output.json").write_text(json.dumps({{
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "images_b64": images_b64,
        "dataframes": dataframes,
        "error": err,
    }}, default=str))
''').strip()


# Wrapper for Code Repository @transform execution. User source files are
# written to /workspace/src.
#
# Two modes (no user code ever runs on the host):
#   "discover" — exec the module to populate the registry, then emit the
#                declared inputs/outputs WITHOUT calling any transform. The
#                host uses this to learn which datasets to provision.
#   "execute"  — exec the module, run every transform reading inputs via
#                load_table, and persist outputs via save_dataframe (the host
#                picks them up from /workspace/output).
TRANSFORM_WRAPPER_TEMPLATE = textwrap.dedent('''
    import builtins, io, json, sys, traceback
    from pathlib import Path

    sys.path.insert(0, "/opt/sdk")
    sys.path.insert(0, "/workspace/src")
    import platform_sdk  # auto-configures from MF_CTX
    import platform_sdk.objects as _objects
    from platform_sdk import transform, Input, Output, registry

    # Transforms commonly reference these without importing them.
    builtins.transform = transform
    builtins.Input = Input
    builtins.Output = Output

    MODE = {mode!r}
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    sys.stdout, sys.stderr = stdout_buf, stderr_buf

    registry.transforms = []
    err = None
    results = []
    declared = []
    try:
        import pandas as pd
        main_file = {main_file!r}
        code = Path("/workspace/src", main_file).read_text(encoding="utf-8")
        ns = {{
            "transform": transform, "Input": Input, "Output": Output,
            "platform_sdk": platform_sdk, "objects": _objects,
            "load_table": platform_sdk.load_table,
        }}
        exec(compile(code, main_file, "exec"), ns)
        if not registry.transforms:
            raise RuntimeError(
                "No @transform-decorated functions found. Did you use @transform?"
            )
        for tx in registry.transforms:
            declared.append({{
                "fn": tx["fn"].__name__,
                "inputs": {{p: inp.dataset_name for p, inp in tx["inputs"].items()}},
                "output": tx["output"].dataset_name,
            }})
        if MODE == "execute":
            for tx in registry.transforms:
                input_dfs = {{
                    p: platform_sdk.load_table(inp.dataset_name)
                    for p, inp in tx["inputs"].items()
                }}
                out_df = tx["fn"](**input_dfs)
                if not isinstance(out_df, pd.DataFrame):
                    raise TypeError(
                        f"Transform {{tx['fn'].__name__!r}} must return a pandas "
                        f"DataFrame, got {{type(out_df)}}"
                    )
                out_name = tx["output"].dataset_name
                platform_sdk.save_dataframe(out_df, out_name)
                results.append({{
                    "output_dataset_name": out_name,
                    "row_count": int(len(out_df)),
                    "columns": list(out_df.columns.astype(str)),
                }})
    except Exception as e:  # noqa: BLE001
        err = f"{{type(e).__name__}}: {{e}}\\n" + traceback.format_exc()

    Path("/workspace/output.json").write_text(json.dumps({{
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "declared": declared,
        "transforms": results,
        "error": err,
    }}, default=str))
''').strip()


# Wrapper for running repository tests under pytest inside the sandbox. User
# test + source files are written to /workspace/src; this runs pytest there and
# writes a normalized result list to /workspace/output.json. No user code ever
# runs on the host.
TEST_WRAPPER_TEMPLATE = textwrap.dedent('''
    import io, json, os, sys, traceback
    from pathlib import Path

    sys.path.insert(0, "/opt/sdk")
    sys.path.insert(0, "/workspace/src")

    # User files are written under /workspace/src (e.g. src/..., tests/...);
    # run pytest from there so relative test paths and `from src...` imports
    # resolve the same way they do on the host execution path.
    os.chdir("/workspace/src")

    test_file = {test_file!r}
    report_path = "/workspace/.report.json"
    results = []
    err = None
    try:
        import pytest
        pytest.main([
            test_file, "--json-report", f"--json-report-file={{report_path}}",
            "--tb=short", "-q",
        ])
        rep = json.loads(Path(report_path).read_text())
        for t in rep.get("tests", []):
            outcome = t.get("outcome", "error")
            status = "passed" if outcome == "passed" else ("failed" if outcome == "failed" else "error")
            message = None
            if outcome != "passed":
                call = t.get("call") or {{}}
                longrepr = call.get("longrepr") or t.get("longrepr")
                if longrepr:
                    message = str(longrepr)[:500]
            results.append({{"name": t.get("nodeid", "unknown"), "status": status, "message": message}})
    except Exception as e:  # noqa: BLE001
        err = f"{{type(e).__name__}}: {{e}}\\n" + traceback.format_exc()

    Path("/workspace/output.json").write_text(json.dumps({{
        "results": results,
        "error": err,
    }}, default=str))
''').strip()


def _wrap(user_code: str) -> str:
    return WRAPPER_TEMPLATE.format(user_code=user_code)


def _docker_visible_path(path: Path) -> Path:
    """Return the path Docker daemon should mount for a worker-local path.

    In docker compose the worker writes under SANDBOX_WORK_ROOT, which is a
    bind mount from SANDBOX_DOCKER_MOUNT_ROOT on the host. The Docker daemon
    sees the host filesystem, not the worker container filesystem.
    """
    if not SANDBOX_DOCKER_MOUNT_ROOT:
        return path
    try:
        relative = path.resolve().relative_to(SANDBOX_WORK_ROOT)
    except ValueError:
        return path
    return Path(SANDBOX_DOCKER_MOUNT_ROOT).resolve() / relative


def _build_command(workspace: Path, data_dir: Path | None, container_name: str | None = None) -> list[str]:
    docker_workspace = _docker_visible_path(workspace)
    cmd = [
        "docker", "run", "--rm",
        "--network=none",
        "--memory=1g",
        "--cpus=1",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=128m",
        "--pids-limit=128",
        "--cap-drop=ALL",
        "--user=65534:65534",
        "--security-opt", "no-new-privileges",
        "-v", f"{docker_workspace}:/workspace:rw",
    ]
    runtime = sandbox_runtime()
    if runtime:
        cmd.insert(3, f"--runtime={runtime}")
    if container_name:
        cmd[2:2] = ["--name", container_name]
    if data_dir is not None:
        cmd += ["-v", f"{_docker_visible_path(data_dir)}:/workspace/data:ro"]
    cmd += [
        "-e", "MF_CTX=/workspace/ctx.json",
        sandbox_image(),
        "python", "/workspace/main.py",
    ]
    return cmd


def _safe_src_file(src_dir: Path, name: str) -> Path:
    raw = Path(name)
    if raw.is_absolute() or not name or name in {".", ".."}:
        raise ValueError(f"unsafe sandbox source path: {name!r}")
    root = src_dir.resolve()
    dest = (src_dir / raw).resolve()
    try:
        dest.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"unsafe sandbox source path: {name!r}") from exc
    if dest == root:
        raise ValueError(f"unsafe sandbox source path: {name!r}")
    return dest


def docker_available() -> bool:
    """True when a Docker daemon is reachable (cheap, cached per process)."""
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is not None:
        return _DOCKER_AVAILABLE
    available = False
    if shutil.which("docker"):
        try:
            proc = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=10, env=_docker_env()
            )
            available = proc.returncode == 0
        except (subprocess.SubprocessError, OSError):
            available = False
    _DOCKER_AVAILABLE = available
    return available


_DOCKER_AVAILABLE: bool | None = None


def parse_output(stdout: bytes, stderr: bytes, returncode: int, workspace: Path) -> dict[str, Any]:
    """Parse the output.json the wrapper writes. Tolerates crashes."""
    output_path = workspace / "output.json"
    if output_path.exists():
        try:
            data = json.loads(output_path.read_text())
        except json.JSONDecodeError as e:
            return {
                "error": f"sandbox produced invalid output.json: {e}",
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            }
        # Pass through whatever the wrapper wrote; if the user code raised,
        # `error` is already populated and stdout/stderr were captured inside.
        data["stdout"] = str(data.get("stdout") or "")[:20000]
        data["stderr"] = str(data.get("stderr") or "")[:20000]
        return data

    # No output.json: container crashed before the wrapper finished writing.
    return {
        "error": "sandbox_crashed" if returncode != 0 else "sandbox_produced_no_output",
        "stdout": stdout.decode(errors="replace")[:20000],
        "stderr": stderr.decode(errors="replace")[:20000],
        "returncode": returncode,
    }


def _run_in_container(
    main_py: str,
    *,
    permitted_datasets: dict[str, str] | None,
    ontology_snapshot: dict[str, Any] | None,
    timeout_s: int,
    extra_src_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Core: provision a workspace, run the sandbox container, collect output.

    `main_py` is the full wrapper program written to /workspace/main.py.
    `extra_src_files` are written under /workspace/src for the wrapper to import.
    """
    SANDBOX_WORK_ROOT.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="mfsbx-", dir=SANDBOX_WORK_ROOT))
    data_dir: Path | None = None
    try:
        workspace.chmod(0o777)

        if extra_src_files:
            src_dir = workspace / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            src_dir.chmod(0o777)
            for name, content in extra_src_files.items():
                dest = _safe_src_file(src_dir, name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")

        (workspace / "main.py").write_text(main_py)

        in_container_paths: dict[str, str] = {}
        if permitted_datasets:
            data_dir = workspace / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            data_dir.chmod(0o755)
            for name, host_path in permitted_datasets.items():
                safe = f"{uuid.uuid4().hex}.parquet"
                shutil.copyfile(host_path, data_dir / safe)
                in_container_paths[name] = f"/workspace/data/{safe}"

        (workspace / "ctx.json").write_text(json.dumps({
            "db_url": None,
            "permitted_datasets": in_container_paths,
            "ontology": ontology_snapshot or {},
        }))

        container_name = f"mfsbx-{uuid.uuid4().hex}"
        try:
            docker_env = _docker_env()
            proc = subprocess.run(
                _build_command(workspace, data_dir, container_name),
                capture_output=True,
                timeout=timeout_s + 5,
                env=docker_env,
            )
            result = parse_output(proc.stdout, proc.stderr, proc.returncode, workspace)
        except subprocess.TimeoutExpired as e:
            subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=10, env=_docker_env())
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=10, env=_docker_env())
            result = {
                "error": "timed_out",
                "stdout": (e.stdout or b"").decode(errors="replace"),
                "stderr": (e.stderr or b"").decode(errors="replace"),
            }
        quota_bytes = max(1, _settings().sandbox_disk_quota_mb) * 1024 * 1024
        used_bytes = _directory_size_bytes(workspace)
        if used_bytes > quota_bytes:
            result = {
                **result,
                "error": f"sandbox disk quota exceeded ({used_bytes} > {quota_bytes} bytes)",
            }

        # Collect any platform_sdk.save_dataframe outputs into a sibling dir
        # so the caller can pick them up after the workspace is wiped.
        saved: dict[str, str] = {}
        output_dir = workspace / "output"
        if output_dir.is_dir():
            keep_dir = Path(tempfile.mkdtemp(prefix="mfsbx-saved-"))
            for f in output_dir.glob("*.parquet"):
                target = keep_dir / f.name
                shutil.copyfile(f, target)
                saved[f.stem] = str(target)
        if saved:
            result["saved_dataframes"] = saved
        return result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_python(
    code: str,
    *,
    permitted_datasets: dict[str, str] | None = None,
    ontology_snapshot: dict[str, Any] | None = None,
    timeout_s: int = 60,
) -> dict[str, Any]:
    """Run user code in a fresh sandbox container.

    `permitted_datasets` maps dataset name -> host parquet file path. Each
    file is copied into a per-run data dir that is mounted read-only at
    /workspace/data inside the container. The wrapper rewrites the paths so
    `platform_sdk.load_table(name)` resolves to the in-container path.

    `ontology_snapshot` is a read-only dict of object types + relationships
    exposed via `platform_sdk.objects`.
    """
    return _run_in_container(
        _wrap(code),
        permitted_datasets=permitted_datasets,
        ontology_snapshot=ontology_snapshot,
        timeout_s=timeout_s,
    )


def run_transform(
    files: dict[str, str],
    main_file: str,
    *,
    mode: str = "execute",
    permitted_datasets: dict[str, str] | None = None,
    ontology_snapshot: dict[str, Any] | None = None,
    timeout_s: int = 120,
) -> dict[str, Any]:
    """Run Code Repository @transform files inside the sandbox container.

    `mode="discover"` populates the registry and returns the declared
    inputs/outputs without running any transform; `mode="execute"` runs them.

    Returns the parsed wrapper output: {declared: [...], transforms: [...],
    saved_dataframes: {stem: host_path}, stdout, stderr, error}. The host maps
    each transform's output dataset name to its saved parquet via
    `safe_output_stem`.
    """
    if mode not in ("discover", "execute"):
        raise ValueError(f"invalid mode: {mode!r}")
    return _run_in_container(
        TRANSFORM_WRAPPER_TEMPLATE.format(main_file=main_file, mode=mode),
        permitted_datasets=permitted_datasets if mode == "execute" else None,
        ontology_snapshot=ontology_snapshot if mode == "execute" else None,
        timeout_s=timeout_s,
        extra_src_files=files,
    )


def run_tests(
    files: dict[str, str],
    test_file: str,
    *,
    timeout_s: int = 60,
) -> dict[str, Any]:
    """Run repository tests under pytest inside the sandbox container.

    Returns the parsed wrapper output: {results: [...], error, stdout, stderr}.
    User test code never runs on the host.
    """
    return _run_in_container(
        TEST_WRAPPER_TEMPLATE.format(test_file=test_file),
        permitted_datasets=None,
        ontology_snapshot=None,
        timeout_s=timeout_s,
        extra_src_files=files,
    )


def safe_output_stem(name: str) -> str:
    """Recompute the parquet stem that platform_sdk.save_dataframe uses for a
    given dataset name, so the host can match saved files to outputs."""
    import re
    return re.sub(r"[^a-z0-9_]", "_", name.lower())[:48].strip("_")
