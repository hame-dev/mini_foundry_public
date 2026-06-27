import pytest

from app.notebooks.sandbox import _run_in_container


def test_extra_src_files_reject_path_traversal():
    with pytest.raises(ValueError, match="unsafe sandbox source path"):
        _run_in_container(
            "print('trusted')",
            permitted_datasets=None,
            ontology_snapshot=None,
            timeout_s=1,
            extra_src_files={"../main.py": "print('override')"},
        )
