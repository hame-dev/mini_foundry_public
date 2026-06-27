import type { ReactNode } from "react";

export type DataTableColumn<T> = {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
};

export function DataTable<T>({
  columns,
  rows,
  empty,
  rowKey,
  className = "",
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  empty?: ReactNode;
  rowKey: (row: T) => string;
  className?: string;
}) {
  if (!rows.length && empty) {
    return <>{empty}</>;
  }
  return (
    <table className={`data-table ${className}`.trim()}>
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} className={column.className}>{column.header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)}>
            {columns.map((column) => (
              <td key={column.key} className={column.className}>{column.cell(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
