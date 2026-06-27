"use client";
import { use, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import ObjectHeader from "@/components/ontology/ObjectHeader";
import ObjectProperties from "@/components/ontology/ObjectProperties";
import RelatedObjectsTable from "@/components/ontology/RelatedObjectsTable";
import ActionTriggerButton from "@/components/ontology/ActionTriggerButton";
import type { ObjectRow, ObjectSchema } from "@/lib/ontology";
import type { OntologyActionOut } from "@/lib/actions";
import { listActions } from "@/lib/actions";

export default function ObjectPage({ params }: { params: Promise<{ type: string; id: string }> }) {
  const { type, id } = use(params);
  const [schema, setSchema] = useState<ObjectSchema | null>(null);
  const [row, setRow] = useState<ObjectRow | null>(null);
  const [actions, setActions] = useState<OntologyActionOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<ObjectSchema>(`/ontology/objects/${type}`).then(setSchema).catch((e) => setError(e.message));
    apiFetch<ObjectRow>(`/objects/${type}/${encodeURIComponent(id)}`).then(setRow).catch((e) => setError(e.message));
    listActions(type).then(setActions).catch(() => setActions([]));
  }, [type, id]);

  if (error) return <div className="text-red-600">{error}</div>;
  if (!schema || !row) return <div>Loading...</div>;

  return (
    <div className="space-y-4">
      <ObjectHeader typeName={type} id={id} displayName={row.display_name} />

      {actions.length > 0 && (
        <section className="flex flex-wrap gap-2">
          {actions.map((a) => (
            <ActionTriggerButton key={a.id} action={a} defaultParams={{ object_type: type, object_id: id }} />
          ))}
        </section>
      )}

      <ObjectProperties properties={row.properties} />

      {row.functions && Object.keys(row.functions).length > 0 && (
        <ObjectProperties properties={row.functions} title="Computed" />
      )}

      {schema.relationships.length > 0 && (
        <section className="space-y-3">
          {schema.relationships.map((r) => (
            <RelatedObjectsTable
              key={r.id}
              typeName={type}
              objectId={id}
              relName={r.name}
              targetType={r.target_type}
            />
          ))}
        </section>
      )}
    </div>
  );
}
