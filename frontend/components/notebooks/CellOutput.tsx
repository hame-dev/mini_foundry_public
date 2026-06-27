"use client";
import type { CellOutput as CellOutputT, NotebookCell } from "@/lib/notebooks";

export default function CellOutput({ cell }: { cell: NotebookCell }) {
  const out: CellOutputT | null = cell.last_output;
  if (cell.last_status === "queued" || cell.last_status === "running") {
    return <div className="text-xs text-gray-500 italic">Running…</div>;
  }
  if (!out) return null;

  if (out.error) {
    return (
      <pre className="text-xs bg-red-50 border border-red-200 rounded p-2 whitespace-pre-wrap">{out.error}</pre>
    );
  }

  return (
    <div className="space-y-2">
      {out.markdown !== undefined && (
        <div className="text-sm whitespace-pre-wrap">{out.markdown}</div>
      )}

      {out.generated_code && (
        <div>
          <div className="text-xs text-gray-500 mb-1">Generated code</div>
          <pre className="text-xs bg-gray-50 border rounded p-2 overflow-auto">{out.generated_code}</pre>
          {out.explanation && <div className="text-xs text-gray-600 mt-1">{out.explanation}</div>}
        </div>
      )}

      {out.columns && out.rows && (
        <div className="overflow-auto border rounded">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-left">
              <tr>{out.columns.map((c) => <th key={c} className="px-3 py-2">{c}</th>)}</tr>
            </thead>
            <tbody>
              {out.rows.slice(0, 100).map((r, i) => (
                <tr key={i} className="border-t">
                  {out.columns!.map((c) => <td key={c} className="px-3 py-1 font-mono">{String(r[c] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {out.stdout && (
        <div>
          <div className="text-xs text-gray-500 mb-1">stdout</div>
          <pre className="text-xs bg-gray-50 border rounded p-2 whitespace-pre-wrap">{out.stdout}</pre>
        </div>
      )}
      {out.stderr && (
        <div>
          <div className="text-xs text-gray-500 mb-1">stderr</div>
          <pre className="text-xs bg-yellow-50 border border-yellow-200 rounded p-2 whitespace-pre-wrap">{out.stderr}</pre>
        </div>
      )}

      {out.dataframes && out.dataframes.map((df, i) => (
        <div key={i}>
          <div className="text-xs text-gray-500 mb-1">{df.name} ({df.total_rows} rows)</div>
          <div className="overflow-auto border rounded">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 text-left">
                <tr>{df.columns.map((c) => <th key={c} className="px-3 py-2">{c}</th>)}</tr>
              </thead>
              <tbody>
                {df.rows.map((r, j) => (
                  <tr key={j} className="border-t">
                    {df.columns.map((c) => <td key={c} className="px-3 py-1 font-mono">{String(r[c] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {out.images_b64 && out.images_b64.map((b64, i) => (
        // Notebook outputs are already-generated data URLs; Next Image cannot optimize them.
        // eslint-disable-next-line @next/next/no-img-element
        <img key={i} src={`data:image/png;base64,${b64}`} alt={`figure ${i}`}
          className="border rounded max-w-full" />
      ))}
    </div>
  );
}
