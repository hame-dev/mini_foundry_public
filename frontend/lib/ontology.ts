export type OntologyProperty = {
  name: string;
  column: string;
  type?: string | null;
};

export type OntologyObjectOut = {
  id: string;
  type_name: string;
  dataset_id: string;
  primary_key: string;
  display_name_column: string | null;
  properties: OntologyProperty[];
  description: string | null;
};

export type OntologyRelationshipOut = {
  id: string;
  source_type: string;
  target_type: string;
  name: string;
  cardinality: string;
  source_key: string;
  target_key: string;
};

export type ObjectSchema = {
  object: OntologyObjectOut;
  relationships: OntologyRelationshipOut[];
};

export type ObjectRow = {
  type: string;
  id: string;
  display_name: string | null;
  properties: Record<string, unknown>;
  functions?: Record<string, unknown>;
  raw: Record<string, unknown>;
};
