import json
import tempfile
from pathlib import Path

from app.notebooks.sandbox import parse_output


def test_parses_well_formed_output_json():
    with tempfile.TemporaryDirectory() as d:
        workspace = Path(d)
        (workspace / "output.json").write_text(json.dumps({
            "stdout": "hi\n", "stderr": "", "images_b64": [], "dataframes": [], "error": None,
        }))
        out = parse_output(b"", b"", 0, workspace)
        assert out["stdout"] == "hi\n"
        assert out["error"] is None


def test_user_code_error_in_output_passthrough():
    with tempfile.TemporaryDirectory() as d:
        workspace = Path(d)
        (workspace / "output.json").write_text(json.dumps({
            "stdout": "", "stderr": "", "images_b64": [], "dataframes": [],
            "error": "ValueError: bad input",
        }))
        out = parse_output(b"", b"", 0, workspace)
        assert "ValueError" in out["error"]


def test_no_output_json_means_crash():
    with tempfile.TemporaryDirectory() as d:
        workspace = Path(d)
        out = parse_output(b"some stdout", b"oom\n", 137, workspace)
        assert out["error"] == "sandbox_crashed"
        assert out["stderr"] == "oom\n"
        assert out["returncode"] == 137


def test_invalid_output_json_handled():
    with tempfile.TemporaryDirectory() as d:
        workspace = Path(d)
        (workspace / "output.json").write_text("{not json")
        out = parse_output(b"", b"", 0, workspace)
        assert "invalid output.json" in out["error"]
