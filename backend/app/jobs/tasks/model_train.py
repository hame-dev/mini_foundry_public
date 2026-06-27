from __future__ import annotations

import os
import uuid
from datetime import datetime

import joblib
import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.data.models import Dataset
from app.jobs.registry import job_task
from app.ml.models import MLModel, MLModelVersion


ARTIFACT_DIR = "/tmp/mini_foundry_models"


@job_task("model_train")
def model_train(session, job, input: dict) -> dict:
    model_id = uuid.UUID(input["model_id"])
    version_id = uuid.UUID(input["version_id"])
    model = session.get(MLModel, model_id)
    version = session.get(MLModelVersion, version_id)
    user_id = uuid.UUID(str(input["user_id"])) if input.get("user_id") else job.user_id
    if model is None or version is None:
        raise RuntimeError("model/version missing")
    ds = session.get(Dataset, model.input_dataset_id)
    if ds is None:
        raise RuntimeError("input dataset missing")
    if user_id is not None:
        from app.permissions.enforcement import require_object_capability_sync
        require_object_capability_sync(session, user_id, "dataset", ds.id, "use_in_sql")

    version.status = "running"
    session.commit()

    settings = get_settings()
    sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
    if user_id is not None:
        from app.permissions.row_policy import apply_row_policies_sync
        sql = apply_row_policies_sync(session, user_id, sql)
    df = pd.read_sql(text(sql), settings.sync_database_url)
    if user_id is not None:
        from app.permissions.masking import apply_masks_to_df, resolve_column_masks_sync
        df = apply_masks_to_df(df, resolve_column_masks_sync(session, user_id, ds.id))
    cols = list(model.feature_columns or [])
    missing = [c for c in [*cols, model.target_column] if c not in df.columns]
    if missing:
        raise RuntimeError(f"missing columns: {', '.join(missing)}")
    train_df = df[[*cols, model.target_column]].dropna()
    if train_df.empty:
        raise RuntimeError("no complete training rows")

    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder

    x = train_df[cols]
    y = train_df[model.target_column]
    cat_cols = [c for c in cols if not pd.api.types.is_numeric_dtype(x[c])]
    num_cols = [c for c in cols if c not in cat_cols]
    pre = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), num_cols),
            ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), cat_cols),
        ],
        remainder="drop",
    )
    estimator = RandomForestClassifier(n_estimators=60, random_state=7) if model.task_type == "classification" else RandomForestRegressor(n_estimators=60, random_state=7)
    pipe = Pipeline([("preprocess", pre), ("model", estimator)])
    test_size = 0.25 if len(train_df) >= 8 else 0.01
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=test_size, random_state=7)
    pipe.fit(x_train, y_train)
    pred = pipe.predict(x_test)
    metrics = {"rows": int(len(train_df)), "features": cols}
    if model.task_type == "classification":
        metrics["accuracy"] = float(accuracy_score(y_test, pred))
    else:
        metrics["mae"] = float(mean_absolute_error(y_test, pred))
        metrics["r2"] = float(r2_score(y_test, pred)) if len(y_test) > 1 else None

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    path = os.path.join(ARTIFACT_DIR, f"{model.id}_{version.version}.joblib")
    joblib.dump({"pipeline": pipe, "features": cols, "task_type": model.task_type}, path)
    version.status = "ready"
    version.metrics = metrics
    version.artifact_path = path
    version.artifact_manifest = {
        "artifact_uri": path,
        "format": "joblib",
        "task_type": model.task_type,
        "model_type": model.model_type,
        "feature_columns": cols,
        "target_column": model.target_column,
        "training_dataset_id": str(model.input_dataset_id),
        "training_dataset_version_id": str(version.training_dataset_version_id) if version.training_dataset_version_id else None,
    }
    version.approval_status = "pending_promotion"
    version.trained_at = datetime.utcnow()
    model.updated_at = datetime.utcnow()
    session.commit()
    return {"model_id": str(model.id), "version_id": str(version.id), "metrics": metrics, "artifact_path": path, "artifact_manifest": version.artifact_manifest}
