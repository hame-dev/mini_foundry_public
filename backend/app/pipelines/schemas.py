"""Pydantic shapes for the pipelines API. Mirrors frontend/lib/pipelines.ts."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Position = dict[str, float]
NodeType = Literal["source", "join", "union", "filter", "formula", "select", "trained_model", "output"]
JoinType = Literal["inner", "left", "right", "full"]
TargetHandle = Literal["left", "right", "in"]


# --- node config payloads ---------------------------------------------------


class SourceConfig(BaseModel):
    dataset_id: uuid.UUID


class JoinConfig(BaseModel):
    join_type: JoinType = "inner"
    left_keys: list[str] = Field(default_factory=list)
    right_keys: list[str] = Field(default_factory=list)
    suggested_from_ontology_relationship_id: uuid.UUID | None = None


class UnionConfig(BaseModel):
    distinct: bool = False


class FilterConfig(BaseModel):
    where: str = ""


class FormulaColumn(BaseModel):
    name: str
    expr: str


class FormulaConfig(BaseModel):
    columns: list[FormulaColumn] = Field(default_factory=list)


class SelectConfig(BaseModel):
    columns: list[str] = Field(default_factory=list)  # empty = *
    rename: dict[str, str] = Field(default_factory=dict)


class TrainedModelConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    prediction_column: str = "prediction"


class OutputConfig(BaseModel):
    name: str
    description: str | None = None
    materialize: Literal["view", "table", "parquet"] = "view"


# --- node / edge / pipeline I/O --------------------------------------------


class NodeIn(BaseModel):
    id: str  # client-supplied; server reuses or assigns a UUID on save
    node_type: NodeType
    position: Position = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class NodeOut(BaseModel):
    id: str
    node_type: NodeType
    position: Position
    config: dict[str, Any]


class EdgeIn(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    target_handle: TargetHandle = "in"


class EdgeOut(EdgeIn):
    pass


class PipelineSummary(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    ai_policy: str
    output_dataset_id: str | None
    materialization_type: str = "view"
    materialized_at: datetime | None = None
    materialized_rows: int | None = None
    last_run_at: datetime | None
    last_run_status: str | None
    created_at: datetime
    updated_at: datetime


class PipelineDetail(PipelineSummary):
    graph: dict[str, Any]
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    last_run_error: str | None = None


class CreatePipelineIn(BaseModel):
    name: str
    description: str | None = None
    workspace_parent_id: uuid.UUID | None = None
    branch_name: str = "main"


class UpdatePipelineIn(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: dict[str, Any] | None = None
    nodes: list[NodeIn] | None = None
    edges: list[EdgeIn] | None = None
    materialization_type: Literal["view", "table", "parquet"] | None = None
    branch_name: str = "main"


class PreviewIn(BaseModel):
    limit: int = 100
    branch_name: str = "main"


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str


class RunOut(BaseModel):
    status: Literal["ok", "error", "queued"]
    output_dataset_id: str | None = None
    output_saved_query_id: str | None = None
    view_name: str | None = None
    columns: list[str] = Field(default_factory=list)
    error: str | None = None
    job_id: str | None = None


# --- AI generation ----------------------------------------------------------


class AiGenerateIn(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str | None = None
    dataset_ids: list[uuid.UUID] | None = None


class AiGenerateOut(BaseModel):
    name: str
    description: str | None
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    provider: str
    model: str
