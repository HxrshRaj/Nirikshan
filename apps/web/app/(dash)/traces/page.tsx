"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { ago, ms } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";

interface TraceRow {
  trace_id: string;
  root_operation: string;
  started_at: string;
  duration_ms: number;
  span_count: number;
  error_count: number;
  status: string;
}
interface Span {
  span_id: string;
  parent_span_id: string | null;
  service: string;
  operation: string;
  started_at: string;
  duration_ms: number;
  status: string;
}
interface TraceDetail {
  trace_id: string;
  root_operation: string;
  duration_ms: number;
  span_count: number;
  error_count: number;
  spans: Span[];
}

export default function TracesPage() {
  const [errOnly, setErrOnly] = useState(false);
  const { data, error, loading } = useApi<TraceRow[]>(
    `/api/traces?minutes=120&limit=60${errOnly ? "&only_errors=true" : ""}`,
    [errOnly]
  );
  const [open, setOpen] = useState<TraceDetail | null>(null);

  async function load(id: string) {
    setOpen(await api.get<TraceDetail>(`/api/traces/${id}`));
  }

  return (
    <div className="space-y-6">
      <Card
        title="Traces"
        action={
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={errOnly} onChange={(e) => setErrOnly(e.target.checked)} /> errors only
          </label>
        }
      >
        {loading && !data ? (
          <Loading />
        ) : error ? (
          <ErrorBox message={error.message} />
        ) : !data || data.length === 0 ? (
          <Empty>No traces.</Empty>
        ) : (
          <Table head={["Trace", "Root operation", "Duration", "Spans", "Errors", "Status", "Started"]}>
            {data.map((t) => (
              <tr key={t.trace_id} className="row cursor-pointer" onClick={() => load(t.trace_id)}>
                <td className="td font-mono text-xs text-accent">{t.trace_id}</td>
                <td className="td">{t.root_operation}</td>
                <td className="td">{ms(t.duration_ms)}</td>
                <td className="td">{t.span_count}</td>
                <td className="td">{t.error_count}</td>
                <td className="td">
                  <span className={t.status === "ERROR" ? "text-bad" : "text-ok"}>{t.status}</span>
                </td>
                <td className="td text-muted">{ago(t.started_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {open && (
        <Card title={<span className="font-mono text-xs">{open.trace_id}</span>}>
          <div className="mb-2 text-xs text-muted">
            {open.root_operation} · {ms(open.duration_ms)} · {open.span_count} spans · {open.error_count} errors
          </div>
          <div className="space-y-1">
            {open.spans.map((s) => {
              const offset =
                (new Date(s.started_at).getTime() - new Date(open.spans[0].started_at).getTime()) /
                Math.max(open.duration_ms, 1);
              const width = Math.max(s.duration_ms / Math.max(open.duration_ms, 1), 0.02);
              return (
                <div key={s.span_id} className="flex items-center gap-2 text-xs">
                  <div className="w-44 shrink-0 truncate text-muted">
                    {s.service} · {s.operation}
                  </div>
                  <div className="relative h-4 flex-1 rounded bg-bg">
                    <div
                      className={`absolute top-0 h-4 rounded ${s.status === "ERROR" ? "bg-bad/70" : "bg-accent/60"}`}
                      style={{ left: `${offset * 100}%`, width: `${width * 100}%` }}
                    />
                  </div>
                  <div className="w-16 shrink-0 text-right text-muted">{ms(s.duration_ms)}</div>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
