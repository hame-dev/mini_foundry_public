"""Unit tests for the sandbox platform_sdk.objects ontology shim.

Imports the sandbox SDK (backend/docker/sandbox/platform_sdk) directly and
verifies it resolves ontology objects from a mounted dataset parquet, with no
network access — exactly how it behaves inside the container.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

SANDBOX_SDK = Path(__file__).resolve().parents[1] / "docker" / "sandbox"


@pytest.fixture
def sdk(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SANDBOX_SDK))
    for name in list(sys.modules):
        if name == "platform_sdk" or name.startswith("platform_sdk."):
            del sys.modules[name]

    import platform_sdk
    import platform_sdk.objects as objects

    df = pd.DataFrame([
        {"customer_id": "C1", "name": "Acme", "status": "active"},
        {"customer_id": "C2", "name": "Beta", "status": "inactive"},
        {"customer_id": "C3", "name": "Cobalt", "status": "active"},
    ])
    parquet = tmp_path / "customers.parquet"
    df.to_parquet(parquet, index=False)

    platform_sdk.configure(
        db_url=None,
        permitted_datasets={"customers": str(parquet)},
        ontology={
            "object_types": [{
                "type_name": "Customer",
                "primary_key": "customer_id",
                "display_name_column": "name",
                "dataset_name": "customers",
                "properties": [],
                "description": None,
            }],
            "relationships": [],
        },
    )
    return platform_sdk, objects


def test_get_by_primary_key(sdk):
    _, objects = sdk
    c = objects.Customer.get("C1")
    assert c["name"] == "Acme"
    assert objects.Customer.get("missing") is None


def test_search_and_list(sdk):
    _, objects = sdk
    actives = objects.Customer.search(status="active")
    assert {c["customer_id"] for c in actives} == {"C1", "C3"}
    assert len(objects.Customer.list()) == 3
    assert len(objects.Customer.list(limit=2)) == 2


def test_unknown_type_raises(sdk):
    _, objects = sdk
    with pytest.raises(AttributeError):
        _ = objects.Vendor


def test_no_snapshot_is_not_implemented(monkeypatch):
    monkeypatch.syspath_prepend(str(SANDBOX_SDK))
    for name in list(sys.modules):
        if name == "platform_sdk" or name.startswith("platform_sdk."):
            del sys.modules[name]
    import platform_sdk
    import platform_sdk.objects as objects

    platform_sdk.configure(db_url=None, permitted_datasets={}, ontology={})
    with pytest.raises(NotImplementedError):
        _ = objects.Customer
