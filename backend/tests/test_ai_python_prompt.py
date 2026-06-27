import json
from app.notebooks.ai_python import build_messages, parse_response


class FakeDataset:
    def __init__(self, id_, name):
        self.id = id_
        self.name = name


class FakeColumn:
    def __init__(self, name, data_type):
        self.name = name
        self.data_type = data_type


def test_build_messages_includes_only_permitted_dataset_columns():
    datasets = [FakeDataset("d1", "orders")]
    cols = {"d1": [FakeColumn("id", "int"), FakeColumn("status", "text")]}
    msgs = build_messages("plot status counts", datasets, cols)
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "orders" in user
    assert "status text" in user
    assert "plot status counts" in user


def test_build_messages_empty_when_no_datasets():
    msgs = build_messages("hi", [], {})
    assert "no datasets" in msgs[1]["content"]


def test_parse_clean_json():
    out = parse_response('{"python": "x = 1", "explanation": "trivial"}')
    assert out == {"python": "x = 1", "explanation": "trivial"}


def test_parse_fenced_json():
    body = "```json\n" + json.dumps({"python": "y = 2", "explanation": ""}) + "\n```"
    out = parse_response(body)
    assert out["python"] == "y = 2"


def test_parse_non_json_treated_as_code():
    out = parse_response("import pandas as pd")
    assert out["python"] == "import pandas as pd"
    assert out["explanation"] == ""
