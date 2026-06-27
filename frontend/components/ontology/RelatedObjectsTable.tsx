"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type Props = {
  typeName: string;
  objectId: string;
  relName: string;
  targetType: string;
};

type RelatedResponse = {
  columns: string[];
  rows: Record<string, unknown>[];
  target_type: string;
  relationship: string;
};

export default function RelatedObjectsTable({ typeName, objectId, relName, targetType }: Props) {
  const [data, setData] = useState<RelatedResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<RelatedResponse>(`/objects/${typeName}/${encodeURIComponent(objectId)}/related/${relName}`)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [typeName, objectId, relName]);

  return (
    <section className="app-card overflow-hidden">
      <div className="section-header">
        <span className="section-header-title">{relName} <span style={{ color: "var(--muted)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>({targetType})</span></span>
        {data && <span className="badge">{data.rows.length}</span>}
      </div>
      {error && <div className="p-3 text-xs" style={{ color: "var(--danger)" }}>{error}</div>}
      {data && (
        <div className="overflow-auto max-h-80">
          <table className="data-table" style={{ fontSize: 12 }}>
            <thead className="sticky top-0">
              <tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => {
                const id = r["id"];
                const cells = data.columns.map((c) => (
                  <td key={c} className="font-mono">{String(r[c] ?? "")}</td>
                ));
                return id !== undefined ? (
                  <tr key={i} className="cursor-pointer" style={{ background: "var(--panel)" }} onMouseEnter={e => (e.currentTarget.style.background = "var(--accent-soft)")} onMouseLeave={e => (e.currentTarget.style.background = "var(--panel)")}>

                    <td colSpan={data.columns.length} className="p-0">
                      <Link
                        className="contents"
                        href={`/objects/${targetType}/${encodeURIComponent(String(id))}`}
                      >
                        <table className="w-full"><tbody><tr>{cells}</tr></tbody></table>
                      </Link>
                    </td>
                  </tr>
                ) : (
                  <tr key={i} className="border-t">{cells}</tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
