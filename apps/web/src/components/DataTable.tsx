import { ReactNode } from "react";

type DataTableProps = {
  headers: ReactNode[];
  rows: ReactNode[][];
  emptyState?: ReactNode;
};

export function DataTable({ headers, rows, emptyState }: DataTableProps) {
  if (rows.length === 0 && emptyState) {
    return <div className="py-12 text-center">{emptyState}</div>;
  }
  return (
    <div className="glass overflow-hidden rounded-md">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-base">
          <thead>
            <tr className="border-b border-mist-12 bg-black/40">
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="px-4 py-3 font-mono text-[12px] uppercase tracking-[0.7px] text-whisper"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr
                key={ri}
                className="group/row relative border-b border-mist-06 last:border-b-0 transition-colors hover:bg-cyan/[0.07]"
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={`px-4 py-3 align-top transition-shadow ${
                      ci === 0
                        ? "group-hover/row:shadow-[inset_3px_0_0_0_var(--color-cyan)]"
                        : ""
                    }`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
