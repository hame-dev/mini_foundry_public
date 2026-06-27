import pytest
from croniter import croniter


@pytest.mark.parametrize(
    "expr,ok",
    [
        ("*/5 * * * *", True),
        ("0 8 * * *", True),
        ("0 2 * * 0", True),
        ("99 * * * *", False),
        ("not a cron", False),
        ("", False),
        ("0 0 32 * *", False),
    ],
)
def test_cron_validation(expr: str, ok: bool):
    assert croniter.is_valid(expr) is ok


def test_known_job_types_present():
    """Importing the registry should auto-register the v0.6 tasks."""
    # Importing the task modules triggers @job_task decoration; the
    # celery_app include list does this at import time.
    import app.jobs.celery_app  # noqa: F401
    from app.jobs.registry import REGISTERED_JOB_TYPES

    expected = {
        "csv_profile", "postgres_discover", "dashboard_cache_refresh",
        "notebook_cell", "scheduled_report",
    }
    assert expected.issubset(REGISTERED_JOB_TYPES), (
        f"missing job types: {expected - REGISTERED_JOB_TYPES}"
    )
