"use client";

import Link from "next/link";
import { use } from "react";
import { useApi } from "@/lib/hooks";
import { num } from "@/lib/format";
import { Card, Empty, ErrorBox, JsonBlock, KV, Loading } from "@/components/ui";
import { MockBadge } from "@/components/badges";

interface ToolCall {
  sequence: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  error: string | null;
  result_summary: string;
  result_rows: number;
  duration_ms: number;
}
interface RunDetail {
  run_id: string;
  kind: string;
  status: string;
  provider: string;
  model: string;
  is_mock: boolean;
  incident_id: string | null;
  prompt_name: string;
  prompt_version: string;
  duration_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  error: string | null;
  result: Record<string, unknown>;
  audit: Record<string, unknown>;
  tool_calls: ToolCall[];
}

export default function RunDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const { data, error, loading } = useApi<RunDetail>(`/api/agents/${runId}`);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data) return <Empty>Not found</Empty>;

  const audit = data.audit as {
    grounded_evidence_ids?: string[];
    evidence_ids_available?: string[];
    warnings?: string[];
  };
  const result = data.result as {
    root_cause?: string;
    confidence?: number;
    hypotheses?: { rank: number; title: string; category: string; confidence: number; evidence: string[] }[];
    recommended_actions?: string[];
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-sm">{data.run_id}</h1>
        <span
          className={`pill ${
            data.status === "COMPLETED"
              ? "border-ok/50 text-ok"
              : data.status === "FAILED"
                ? "border-bad/50 text-bad"
                : "border-warn/50 text-warn"
          }`}
        >
          {data.status}
        </span>
        <MockBadge isMock={data.is_mock} />
        {data.incident_id && (
          <Link href={`/incidents`} className="text-xs text-accent">
            → incident
          </Link>
        )}
      </div>

      <Card title="Run metadata">
        <div className="kv">
          <KV k="Kind">{data.kind}</KV>
          <KV k="Provider">{data.provider} / {data.model}</KV>
          <KV k="Prompt">{data.prompt_name}@{data.prompt_version}</KV>
          <KV k="Duration">{data.duration_ms ? `${num(data.duration_ms, 0)} ms` : "—"}</KV>
          <KV k="Tokens">{data.input_tokens} in / {data.output_tokens} out</KV>
          <KV k="Est. cost">${data.estimated_cost_usd.toFixed(6)}</KV>
          {data.error && <KV k="Error">{data.error}</KV>}
        </div>
      </Card>

      {result.hypotheses && (
        <Card title="Conclusion">
          <div className="mb-2 text-sm">
            <b>{result.root_cause}</b> — confidence {result.confidence?.toFixed(2)}
          </div>
          <ol className="ml-4 list-decimal text-sm text-muted">
            {result.hypotheses.map((h) => (
              <li key={h.rank}>
                {h.title} <span className="text-xs">({h.category}, {h.confidence.toFixed(2)})</span>
                {h.evidence?.length ? <span className="text-xs"> · {h.evidence.join(", ")}</span> : null}
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Card title="Evidence tools called (audit trail)">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-panel2">
              <tr>
                {["#", "Tool", "Arguments", "OK", "Rows", "Summary", "ms"].map((h) => (
                  <th key={h} className="th">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.tool_calls.map((c) => (
                <tr key={c.sequence} className="row">
                  <td className="td">{c.sequence}</td>
                  <td className="td font-mono text-xs">{c.tool_name}</td>
                  <td className="td font-mono text-xs text-muted">{JSON.stringify(c.arguments)}</td>
                  <td className="td">{c.ok ? "✓" : <span className="text-bad">✗</span>}</td>
                  <td className="td">{c.result_rows}</td>
                  <td className="td text-xs text-muted">{c.result_summary || c.error}</td>
                  <td className="td text-muted">{c.duration_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Evidence grounding">
          <div className="text-xs text-muted">
            <b>Grounded ({audit.grounded_evidence_ids?.length ?? 0}):</b>{" "}
            {audit.grounded_evidence_ids?.join(", ") || "—"}
          </div>
          <div className="mt-2 text-xs text-muted">
            <b>Available ({audit.evidence_ids_available?.length ?? 0}):</b>{" "}
            {audit.evidence_ids_available?.join(", ") || "—"}
          </div>
          {audit.warnings?.length ? (
            <div className="mt-2 text-xs text-warn">Warnings: {audit.warnings.join("; ")}</div>
          ) : null}
        </Card>
        <Card title="Raw audit">
          <JsonBlock data={data.audit} />
        </Card>
      </div>
    </div>
  );
}
