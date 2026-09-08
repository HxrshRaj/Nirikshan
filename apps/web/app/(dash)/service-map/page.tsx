"use client";

import { useState } from "react";
import { usePolling, useApi } from "@/lib/hooks";
import { ms, pct } from "@/lib/format";
import { Card, Empty, ErrorBox, KV, Loading } from "@/components/ui";
import { HealthDot } from "@/components/badges";
import { ServiceGraph, GraphEdge, GraphNode } from "@/components/ServiceGraph";

export default function ServiceMapPage() {
  const { data, error, loading } = usePolling<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
    "/api/service-map",
    8000
  );
  const [sel, setSel] = useState<string | null>(null);
  const detail = useApi<{
    direct_dependents: string[];
    indirect_dependents: string[];
    downstream_dependencies: string[];
    impacted_user_facing: string[];
    total_impacted: number;
  }>(sel ? `/api/services/${sel}/blast-radius` : null, [sel]);
  const health = useApi<{ health: string; error_rate: number | null; latency_p95_ms: number | null; reasons: string[] }>(
    sel ? `/api/services/${sel}/health` : null,
    [sel]
  );

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data || data.nodes.length === 0) return <Empty>No topology — seed the demo from Settings.</Empty>;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <Card title="Dependency graph" action={<span className="text-xs text-muted">click a service</span>}>
        <ServiceGraph nodes={data.nodes} edges={data.edges} onSelect={setSel} selected={sel} />
        <div className="mt-2 flex gap-4 text-xs text-muted">
          <span>— critical edge</span>
          <span>· · async / non-critical</span>
          <span className="text-bad">● unhealthy</span>
          <span className="text-warn">● degraded</span>
          <span className="text-ok">● healthy</span>
        </div>
      </Card>

      <Card title={sel ? sel : "Select a service"}>
        {!sel ? (
          <Empty>Pick a node to see health &amp; blast radius.</Empty>
        ) : (
          <div className="space-y-3">
            {health.data && (
              <div className="kv text-sm">
                <KV k="Health"><HealthDot health={health.data.health} /></KV>
                <KV k="Error rate">{pct(health.data.error_rate ?? 0, 2)}</KV>
                <KV k="p95 latency">{ms(health.data.latency_p95_ms)}</KV>
              </div>
            )}
            {health.data?.reasons?.length ? (
              <ul className="ml-4 list-disc text-xs text-muted">
                {health.data.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
            {detail.data && (
              <div className="kv text-sm">
                <KV k="Direct dependents">{detail.data.direct_dependents.join(", ") || "—"}</KV>
                <KV k="Indirect dependents">{detail.data.indirect_dependents.join(", ") || "—"}</KV>
                <KV k="Downstream deps">{detail.data.downstream_dependencies.join(", ") || "—"}</KV>
                <KV k="User-facing impact">{detail.data.impacted_user_facing.join(", ") || "—"}</KV>
                <KV k="Total impacted">{detail.data.total_impacted}</KV>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
