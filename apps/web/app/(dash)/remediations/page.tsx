"use client";

import Link from "next/link";
import { usePolling } from "@/lib/hooks";
import { time } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";
import { RiskBadge } from "@/components/badges";

interface Rem {
  ref: string;
  incident_id: string;
  action_name: string;
  parameters: Record<string, unknown>;
  risk: string;
  status: string;
  mode: string;
  is_reversible: boolean;
  created_at: string;
  policy_findings: { level: string; code: string; message: string }[];
  approvals: { decision: string; actor: string; at: string }[];
  executions: { kind: string; ok: boolean; result: string; verification: { summary?: string } }[];
}

export default function RemediationsPage() {
  const { data, error, loading } = usePolling<Rem[]>("/api/remediations", 6000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data || data.length === 0) return <Empty>No remediations proposed yet.</Empty>;

  return (
    <div className="space-y-4">
      {data.map((r) => (
        <Card
          key={r.ref}
          title={
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-accent">{r.ref}</span>
              <span>{r.action_name}</span>
              <RiskBadge risk={r.risk} />
              <span className="pill border-border text-muted">{r.status}</span>
              <span className="pill border-border text-muted">mode {r.mode}</span>
            </span>
          }
          action={<Link href={`/incidents`} className="text-xs text-accent">incident →</Link>}
        >
          <div className="text-xs text-muted">params {JSON.stringify(r.parameters)} · created {time(r.created_at)}</div>
          {r.policy_findings.length > 0 && (
            <ul className="mt-2 ml-4 list-disc text-xs">
              {r.policy_findings.map((f, i) => (
                <li key={i} className={f.level === "block" ? "text-bad" : f.level === "warn" ? "text-warn" : "text-muted"}>
                  [{f.code}] {f.message}
                </li>
              ))}
            </ul>
          )}
          {r.approvals.length > 0 && (
            <div className="mt-2 text-xs text-muted">
              {r.approvals.map((a, i) => (
                <div key={i}>
                  {a.decision} by {a.actor} · {time(a.at)}
                </div>
              ))}
            </div>
          )}
          {r.executions.length > 0 && (
            <div className="mt-2 text-xs">
              {r.executions.map((e, i) => (
                <div key={i} className={e.ok ? "text-ok" : "text-bad"}>
                  {e.kind}: {e.result} {e.verification?.summary ? `· ${e.verification.summary}` : ""}
                </div>
              ))}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}
