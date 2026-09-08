"use client";

import Link from "next/link";
import { usePolling } from "@/lib/hooks";
import { ago, num } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Stat, Table } from "@/components/ui";
import { MockBadge } from "@/components/badges";

interface Run {
  run_id: string;
  kind: string;
  incident_id: string | null;
  status: string;
  provider: string;
  model: string;
  is_mock: boolean;
  duration_ms: number | null;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  finished_at: string | null;
  error: string | null;
}
interface Ops {
  window_hours: number;
  agent_runs: {
    total: number;
    completed: number;
    failed: number;
    avg_duration_ms: number;
    p95_duration_ms: number;
    total_tool_calls: number;
    by_kind: Record<string, number>;
  };
  llm_calls: {
    total: number;
    mock: number;
    total_cost_usd: number;
    by_provider: Record<string, { calls: number; avg_latency_ms: number; cost_usd: number; errors: number }>;
  };
}

export default function InvestigationsPage() {
  const runs = usePolling<Run[]>("/api/agents?limit=100", 6000);
  const ops = usePolling<Ops>("/api/agents/ops/summary?hours=24", 15000);

  return (
    <div className="space-y-6">
      {ops.data && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="Runs (24h)" value={ops.data.agent_runs.total} />
          <Stat label="Completed" value={ops.data.agent_runs.completed} tone="ok" />
          <Stat label="Failed" value={ops.data.agent_runs.failed} tone={ops.data.agent_runs.failed ? "bad" : "default"} />
          <Stat label="Avg duration" value={`${num(ops.data.agent_runs.avg_duration_ms, 0)} ms`} />
          <Stat label="LLM cost (24h)" value={`$${ops.data.llm_calls.total_cost_usd.toFixed(4)}`} />
        </div>
      )}

      <Card title="Agent runs">
        {runs.loading && !runs.data ? (
          <Loading />
        ) : runs.error ? (
          <ErrorBox message={runs.error.message} />
        ) : !runs.data || runs.data.length === 0 ? (
          <Empty>No agent runs yet.</Empty>
        ) : (
          <Table head={["Run", "Kind", "Status", "Provider", "Tools", "Tokens in/out", "Cost", "Duration", "When"]}>
            {runs.data.map((r) => (
              <tr key={r.run_id} className="row">
                <td className="td font-mono text-xs">
                  <Link href={`/investigations/${r.run_id}`} className="text-accent">
                    {r.run_id}
                  </Link>
                </td>
                <td className="td text-muted">{r.kind}</td>
                <td className="td">
                  <span
                    className={`pill ${
                      r.status === "COMPLETED"
                        ? "border-ok/50 text-ok"
                        : r.status === "FAILED"
                          ? "border-bad/50 text-bad"
                          : "border-warn/50 text-warn"
                    }`}
                  >
                    {r.status}
                  </span>{" "}
                  <MockBadge isMock={r.is_mock} />
                </td>
                <td className="td text-muted">{r.provider}/{r.model}</td>
                <td className="td">{r.tool_call_count}</td>
                <td className="td text-muted">
                  {r.input_tokens}/{r.output_tokens}
                </td>
                <td className="td text-muted">${r.estimated_cost_usd.toFixed(5)}</td>
                <td className="td text-muted">{r.duration_ms ? `${num(r.duration_ms, 0)} ms` : "—"}</td>
                <td className="td text-muted">{ago(r.finished_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
