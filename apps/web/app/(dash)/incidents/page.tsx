"use client";

import Link from "next/link";
import { useState } from "react";
import { usePolling } from "@/lib/hooks";
import { ago, dur } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";
import { SeverityBadge, StatusBadge } from "@/components/badges";

interface IncidentSummary {
  ref: string;
  title: string;
  severity: string;
  status: string;
  service: string;
  detected_at: string;
  confidence: number | null;
  alert_count: number;
  duration_seconds: number | null;
}

export default function IncidentsPage() {
  const [openOnly, setOpenOnly] = useState(false);
  const { data, error, loading } = usePolling<{ items: IncidentSummary[]; total: number }>(
    `/api/incidents?limit=100${openOnly ? "&open_only=true" : ""}`,
    6000
  );

  return (
    <Card
      title="Incidents"
      action={
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
          open only
        </label>
      }
    >
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error.message} />
      ) : !data || data.items.length === 0 ? (
        <Empty>No incidents.</Empty>
      ) : (
        <Table head={["Ref", "Severity", "Title", "Service", "Status", "Alerts", "Confidence", "Age", "Duration"]}>
          {data.items.map((i) => (
            <tr key={i.ref} className="row">
              <td className="td font-mono text-xs">
                <Link href={`/incidents/${i.ref}`} className="text-accent">
                  {i.ref}
                </Link>
              </td>
              <td className="td"><SeverityBadge severity={i.severity} /></td>
              <td className="td">{i.title}</td>
              <td className="td text-muted">{i.service}</td>
              <td className="td"><StatusBadge status={i.status} /></td>
              <td className="td">{i.alert_count}</td>
              <td className="td">{i.confidence?.toFixed(2) ?? "—"}</td>
              <td className="td text-muted">{ago(i.detected_at)}</td>
              <td className="td text-muted">{i.duration_seconds ? dur(Math.round(i.duration_seconds)) : "—"}</td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}
