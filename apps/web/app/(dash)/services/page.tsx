"use client";

import Link from "next/link";
import { usePolling } from "@/lib/hooks";
import { ms, pct } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";
import { HealthDot } from "@/components/badges";

interface Svc {
  id: string;
  name: string;
  display_name: string;
  kind: string;
  tier: number;
  owner_team: string;
  health: string;
  slo_latency_ms_p95: number;
  slo_error_rate: number;
  depends_on: string[];
  upstream_of: string[];
}

export default function ServicesPage() {
  const { data, error, loading } = usePolling<Svc[]>("/api/services", 8000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data || data.length === 0) return <Empty>No services — seed the demo from Settings.</Empty>;

  return (
    <Card title="Services">
      <Table head={["Service", "Kind", "Tier", "Team", "Health", "SLO p95", "SLO err", "Depends on", "Called by"]}>
        {data.map((s) => (
          <tr key={s.id} className="row">
            <td className="td">
              <Link href={`/service-map?focus=${s.name}`} className="text-accent">
                {s.display_name}
              </Link>
              <div className="text-xs text-muted">{s.name}</div>
            </td>
            <td className="td text-muted">{s.kind}</td>
            <td className="td">{s.tier}</td>
            <td className="td text-muted">{s.owner_team || "—"}</td>
            <td className="td"><HealthDot health={s.health} /></td>
            <td className="td text-muted">{ms(s.slo_latency_ms_p95)}</td>
            <td className="td text-muted">{pct(s.slo_error_rate, 1)}</td>
            <td className="td text-xs text-muted">{s.depends_on.join(", ") || "—"}</td>
            <td className="td text-xs text-muted">{s.upstream_of.join(", ") || "—"}</td>
          </tr>
        ))}
      </Table>
    </Card>
  );
}
