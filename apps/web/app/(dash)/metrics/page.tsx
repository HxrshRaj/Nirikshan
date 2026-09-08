"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { num } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading } from "@/components/ui";
import { Sparkline } from "@/components/Sparkline";

const METRICS = [
  "request_latency_ms",
  "error_rate",
  "request_count",
  "database_connections",
  "cpu_usage",
  "memory_usage",
  "queue_depth",
];

export default function MetricsPage() {
  const services = useApi<{ name: string; display_name: string }[]>("/api/services");
  const [service, setService] = useState("payment-service");
  const [minutes, setMinutes] = useState(120);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select className="input" value={service} onChange={(e) => setService(e.target.value)}>
          {(services.data || []).map((s) => (
            <option key={s.name} value={s.name}>
              {s.display_name}
            </option>
          ))}
        </select>
        <select className="input" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
          {[30, 60, 120, 360, 1440].map((m) => (
            <option key={m} value={m}>
              last {m}m
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {METRICS.map((m) => (
          <MetricCard key={m} service={service} metric={m} minutes={minutes} />
        ))}
      </div>
    </div>
  );
}

function MetricCard({ service, metric, minutes }: { service: string; metric: string; minutes: number }) {
  const agg = metric === "request_latency_ms" ? "p95" : "avg";
  const { data, error, loading } = useApi<{
    points: { ts: string; value: number }[];
    unit: string;
  }>(`/api/metrics/series?service=${service}&metric=${metric}&minutes=${minutes}&aggregation=${agg}`, [
    service,
    metric,
    minutes,
  ]);

  const last = data?.points.at(-1)?.value;
  return (
    <Card title={<span className="font-mono text-xs">{metric}</span>}>
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorBox message={error.message} />
      ) : !data || data.points.length < 2 ? (
        <Empty>no data</Empty>
      ) : (
        <>
          <div className="mb-1 text-lg font-semibold">
            {num(last, 3)} <span className="text-xs text-muted">{data.unit}</span>
          </div>
          <Sparkline points={data.points} width={320} height={72} />
          <div className="mt-1 text-xs text-muted">{agg} · {data.points.length} points</div>
        </>
      )}
    </Card>
  );
}
