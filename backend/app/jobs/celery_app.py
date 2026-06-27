"""Celery application factory.

Imports the task modules so Celery registers them on import. The web process
also imports `celery_app` (to call `.send_task`), so this module must not
trigger any DB or IO at import time.
"""
from celery import Celery
from app.config import get_settings
import importlib


_settings = get_settings()

celery_app = Celery(
    "mini_foundry",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "app.jobs.tasks.csv_profile",
        "app.jobs.tasks.postgres_discover",
        "app.jobs.tasks.dashboard_cache_refresh",
        "app.jobs.tasks.notebook_cell",
        "app.jobs.tasks.run_pipeline",
        "app.jobs.tasks.scheduled_report",
        "app.jobs.tasks.run_workflow",
        "app.jobs.tasks.model_train",
        "app.jobs.tasks.ontology_webhook",
        "app.jobs.tasks.code_transform",
        "app.jobs.tasks.code_test",
    ],
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=900,        # hard 15 min
    task_soft_time_limit=600,   # soft 10 min
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)

for module_name in celery_app.conf.imports or celery_app.conf.include or celery_app.loader.default_modules:
    importlib.import_module(module_name)
