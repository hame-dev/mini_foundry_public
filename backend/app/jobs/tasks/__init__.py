"""Import task modules so registry-backed metadata sees all job types."""

from app.jobs.tasks import csv_profile  # noqa: F401
from app.jobs.tasks import dashboard_cache_refresh  # noqa: F401
from app.jobs.tasks import model_train  # noqa: F401
from app.jobs.tasks import notebook_cell  # noqa: F401
from app.jobs.tasks import postgres_discover  # noqa: F401
from app.jobs.tasks import run_pipeline  # noqa: F401
from app.jobs.tasks import run_workflow  # noqa: F401
from app.jobs.tasks import scheduled_report  # noqa: F401
