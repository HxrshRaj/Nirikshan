"use client";

import Link from "next/link";
import { usePolling } from "@/lib/hooks";
import { ago, ms, num, pct } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Stat } from "@/components/ui";
import { HealthDot, SeverityBadge, StatusBadge } from "@/components/badges";

interface Overview {
  active_incidents: number;
  critical_incidents: number;
  services_total: number;
  services_degraded: number;
  error_rate_avg: number;
  latency_p95_avg_ms: number;
  alert_volume_24h: number;
  anomalies_1h: number;
  pending_approvals: number;
  open_incidents: {
    ref: string;
    title: string;
    severity: string;
    status: string;
    service: string;
    detected_at: string;
    confidence: number | null;
  }[];
  service_health: {
    service: string;
    display_name: string;
    tier: number;
    health: string;
    error_rate: number | null;
    latency_p95_ms: number | null;
  }[];
  recent_deployments: { ref: string; service: string; version: string; started_at: string; status: string }[];
  recent_investigations: {
    run_id: string;
    incident_id: string;
    status: string;
    is_mock: boolean;
    root_cause: string | null;
    confidence: number | null;
  }[];
}

export default function OverviewPage() {
  const { data, error, loading } = usePolling<Overview>("/api/overview", 5000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data) return <Empty>No data yet — seed the demo from Settings.</Empty>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-5">
        <Stat label="Active incidents" value={data.active_incidents} tone={data.active_incidents ? "bad" : "ok"} />
        <Stat label="Critical (SEV-1/2)" value={data.critical_incidents} tone={data.critical_incidents ? "bad" : "default"} />
        <Stat
          label="Services degraded"
          value={`${data.services_degraded}/${data.services_total}`}
          tone={data.services_degraded ? "warn" : "ok"}
        />
        <Stat label="Avg error rate" value={pct(data.error_rate_avg)} tone={data.error_rate_avg > 0.05 ? "bad" : "default"} />
        <Stat label="Avg p95 latency" value={ms(data.latency_p95_avg_ms)} />
        <Stat label="Alerts (24h)" value={num(data.alert_volume_24h, 0)} />
        <Stat label="Anomalies (1h)" value={num(data.anomalies_1h, 0)} />
        <Stat label="Pending approvals" value={data.pending_approvals} tone={data.pending_approvals ? "warn" : "default"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Open incidents" action={<Link href="/incidents" className="text-xs text-accent">all →</Link>}>
          {data.open_incidents.length === 0 ? (
            <Empty>No open incidents. All clear.</Empty>
          ) : (
            <div className="space-y-2">
              {data.open_incidents.map((i) => (
                <Link
                  key={i.ref}
                  href={`/incidents/${i.ref}`}
                  className="row flex items-center justify-between rounded-md px-2 py-2"
                >
                  <div className="flex items-center gap-3">
                    <SeverityBadge severity={i.severity} />
                    <div>
                      <div className="text-sm">{i.title}</div>
                      <div className="text-xs text-muted">
                        {i.ref} · {i.service} · {ago(i.detected_at)}
                      </div>
                    </div>
                  </div>
                  <StatusBadge status={i.status} />
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card title="AI investigations" action={<Link href="/investigations" className="text-xs text-accent">all →</Link>}>
          {data.recent_investigations.length === 0 ? (
            <Empty>No investigations run yet.</Empty>
          ) : (
            <div className="space-y-2">
              {data.recent_investigations.map((r) => (
                <Link
                  key={r.run_id}
                  href={`/investigations/${r.run_id}`}
                  className="row block rounded-md px-2 py-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs text-muted">{r.run_id}</span>
                    <span className={`pill ${r.status === "COMPLETED" ? "border-ok/50 text-ok" : r.status === "FAILED" ? "border-bad/50 text-bad" : "border-warn/50 text-warn"}`}>
                      {r.status}
                    </span>
                  </div>
                  <div className="mt-1 text-sm">{r.root_cause || "—"}</div>
                  <div className="text-xs text-muted">
                    confidence {r.confidence?.toFixed(2) ?? "—"} {r.is_mock ? "· demo/mock" : ""}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card title="Service health">
          <div className="space-y-1">
            {data.service_health.map((s) => (
              <div key={s.service} className="row flex items-center justify-between rounded-md px-2 py-1.5">
                <div className="flex items-center gap-2">
                  <HealthDot health={s.health} />
                  <span className="text-sm">{s.display_name}</span>
                  <span className="pill border-border text-muted">tier {s.tier}</span>
                </div>
                <div className="text-xs text-muted">
                  err {pct(s.error_rate ?? 0, 1)} · p95 {ms(s.latency_p95_ms)}
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Recent deployments" action={<Link href="/deployments" className="text-xs text-accent">all →</Link>}>
          {data.recent_deployments.length === 0 ? (
            <Empty>No deployments recorded.</Empty>
          ) : (
            <div className="space-y-1">
              {data.recent_deployments.map((d) => (
                <div key={d.ref} className="row flex items-center justify-between rounded-md px-2 py-1.5">
                  <span className="text-sm">
                    {d.service} <span className="font-mono text-xs text-accent">{d.version}</span>
                  </span>
                  <span className="text-xs text-muted">
                    {d.status} · {ago(d.started_at)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
