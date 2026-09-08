"use client";

import { usePolling } from "@/lib/hooks";
import { ago, time } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";

interface Dep {
  ref: string;
  service: string;
  version: string;
  previous_version: string | null;
  commit_sha: string | null;
  change_summary: string;
  started_at: string;
  status: string;
  triggered_by: string;
}

export default function DeploymentsPage() {
  const { data, error, loading } = usePolling<Dep[]>("/api/deployments?limit=100", 10000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data || data.length === 0) return <Empty>No deployments recorded.</Empty>;

  return (
    <Card title="Deployments">
      <Table head={["Ref", "Service", "Version", "Previous", "Commit", "By", "Status", "Started", "Change"]}>
        {data.map((d) => (
          <tr key={d.ref} className="row">
            <td className="td font-mono text-xs">{d.ref}</td>
            <td className="td">{d.service}</td>
            <td className="td font-mono text-xs text-accent">{d.version}</td>
            <td className="td font-mono text-xs text-muted">{d.previous_version || "—"}</td>
            <td className="td font-mono text-xs text-muted">{d.commit_sha?.slice(0, 8) || "—"}</td>
            <td className="td text-muted">{d.triggered_by}</td>
            <td className="td">
              <span
                className={`pill ${
                  d.status === "SUCCEEDED"
                    ? "border-ok/50 text-ok"
                    : d.status === "ROLLED_BACK"
                      ? "border-warn/50 text-warn"
                      : "border-bad/50 text-bad"
                }`}
              >
                {d.status}
              </span>
            </td>
            <td className="td text-muted" title={time(d.started_at)}>
              {ago(d.started_at)}
            </td>
            <td className="td text-xs text-muted">{d.change_summary || "—"}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
