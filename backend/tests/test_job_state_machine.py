import pytest

from app.jobs.models import JOB_TRANSITIONS, Job, JobLogEvent
from app.jobs.service_sync import (
    InvalidJobTransition,
    mark_failed,
    mark_running,
    mark_succeeded,
)


class _Session:
    """Minimal stand-in: the sync helpers only mutate fields and call commit;
    they don't actually require a real session unless report_progress is used.
    """
    def __init__(self) -> None:
        self.added = []

    def commit(self) -> None:
        pass

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def query(self, _model):
        class _Query:
            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def first(self):
                return None

        return _Query()


def _job(status: str = "queued") -> Job:
    import uuid

    j = Job()
    j.id = uuid.uuid4()
    j.status = status
    j.attempt = 1
    j.celery_task_id = str(j.id)
    return j


def test_queued_to_running_ok():
    j = _job("queued")
    session = _Session()
    mark_running(session, j)
    assert j.status == "running"
    assert j.started_at is not None
    assert any(isinstance(obj, JobLogEvent) and obj.message == "running" for obj in session.added)


def test_running_to_succeeded_ok():
    j = _job("running")
    mark_succeeded(_Session(), j, {"k": "v"})
    assert j.status == "succeeded"
    assert j.output == {"k": "v"}
    assert j.finished_at is not None


def test_mark_succeeded_wraps_non_dict_output():
    j = _job("running")
    mark_succeeded(_Session(), j, 42)
    assert j.output == {"result": 42}


def test_invalid_transition_from_succeeded():
    j = _job("succeeded")
    with pytest.raises(InvalidJobTransition):
        mark_running(_Session(), j)


def test_mark_failed_from_running():
    j = _job("running")
    mark_failed(_Session(), j, "boom")
    assert j.status == "failed"
    assert "boom" in (j.error or "")


def test_mark_failed_is_idempotent_on_terminal():
    j = _job("succeeded")
    mark_failed(_Session(), j, "should be ignored")
    assert j.status == "succeeded"


def test_transition_map_is_consistent():
    # Terminal states must have empty outgoing transitions.
    for terminal in ("succeeded", "failed", "cancelled", "timed_out"):
        assert JOB_TRANSITIONS[terminal] == set()
    # queued and running must be able to reach failure.
    assert "failed" in JOB_TRANSITIONS["queued"]
    assert "failed" in JOB_TRANSITIONS["running"]
