"use client";

import { useApi } from "@/lib/hooks";
import { time } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";
import { SeverityBadge } from "@/components/badges";

interface HistItem {
  ref: string;
  title: string;
  severity: string;
  status: string;
  service: string;
  detected_at: string;
  resolved_at: string | null;
  duration_seconds: number | null;
}

export default function HistoryPage() {
  const { data, error, loading } = useApi<{ items: HistItem[]; total: number }>(
    "/api/incidents?status=CLOSED&limit=100"
  );
  const resolved = useApi<{ items: HistItem[] }>("/api/incidents?status=RESOLVED&limit=100");

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  const rows = [...(data?.items || []), ...(resolved.data?.items || [])];
  if (rows.length === 0) return <Empty>No resolved or closed incidents yet.</Empty>;

  return (
    <Card title="Incident History">
      <p className="mb-3 text-xs text-muted">
        Closed incidents are distilled into the incident-memory / RAG store, which the investigator
        retrieves as supporting context for similar future incidents.
      </p>
      <Table head={["Ref", "Severity", "Title", "Service", "Status", "Detected", "Resolved"]}>
        {rows.map((i) => (
          <tr key={i.ref} className="row">
            <td className="td font-mono text-xs">{i.ref}</td>
            <td className="td"><SeverityBadge severity={i.severity} /></td>
            <td className="td">{i.title}</td>
            <td className="td text-muted">{i.service}</td>
            <td className="td text-muted">{i.status}</td>
            <td className="td text-muted">{time(i.detected_at)}</td>
            <td className="td text-muted">{time(i.resolved_at)}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
