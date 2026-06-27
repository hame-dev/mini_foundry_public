export type MLModel = {
  id: string;
  name: string;
  description: string | null;
  task_type: "classification" | "regression";
  model_type: string;
  input_dataset_id: string | null;
  target_column: string;
  feature_columns: string[];
  owner_id: string | null;
  created_at: string;
  updated_at: string;
};

export type MLModelVersion = {
  id: string;
  model_id: string;
  version: number;
  status: string;
  training_config: Record<string, unknown>;
  metrics: Record<string, unknown> | null;
  artifact_path: string | null;
  job_id: string | null;
  created_at: string;
  trained_at: string | null;
};

export type MLModelDetail = {
  model: MLModel;
  versions: MLModelVersion[];
  latest_metrics: Record<string, unknown> | null;
  input_dataset: Record<string, unknown> | null;
  feature_metadata: Array<Record<string, unknown>>;
  build_job: Record<string, unknown> | null;
};
