"use client";

import { usePolling } from "@/lib/hooks";
import { ago, num } from "@/lib/format";
import { Card, Empty, ErrorBox, Loading, Table } from "@/components/ui";

interface Alert {
  ref: string;
  service: string;
  title: string;
  signal_kind: string;
  severity: string;
  state: string;
  observed_value: number | null;
  threshold: number | null;
  fired_at: string;
  incident_id: string | null;
}
interface Anomaly {
  id: string;
  service: string;
  metric_name: string;
  method: string;
  observed_value: number;
  expected_high: number;
  score: number;
  confidence: number;
  direction: string;
  detected_at: string;
}

export default function AlertsPage() {
  const alerts = usePolling<Alert[]>("/api/alerts?limit=100", 6000);
  const anomalies = usePolling<Anomaly[]>("/api/anomalies?minutes=240&limit=100", 6000);

  return (
    <div className="space-y-6">
      <Card title="Alerts">
        {alerts.loading && !alerts.data ? (
          <Loading />
        ) : alerts.error ? (
          <ErrorBox message={alerts.error.message} />
        ) : !alerts.data || alerts.data.length === 0 ? (
          <Empty>No alerts.</Empty>
        ) : (
          <Table head={["Ref", "State", "Severity", "Service", "Signal", "Observed", "Threshold", "Fired", "Incident"]}>
            {alerts.data.map((a) => (
              <tr key={a.ref} className="row">
                <td className="td font-mono text-xs">{a.ref}</td>
                <td className="td">
                  <span className={`pill ${a.state === "FIRING" ? "border-bad/50 text-bad" : "border-ok/50 text-ok"}`}>
                    {a.state}
                  </span>
                </td>
                <td className="td">{a.severity}</td>
                <td className="td text-muted">{a.service}</td>
                <td className="td text-muted">{a.signal_kind}</td>
                <td className="td">{num(a.observed_value)}</td>
                <td className="td text-muted">{num(a.threshold)}</td>
                <td className="td text-muted">{ago(a.fired_at)}</td>
                <td className="td">
                  {a.incident_id ? <span className="text-accent">linked</span> : <span className="text-muted">—</span>}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Anomalies (last 4h)">
        {anomalies.loading && !anomalies.data ? (
          <Loading />
        ) : !anomalies.data || anomalies.data.length === 0 ? (
          <Empty>No anomalies detected.</Empty>
        ) : (
          <Table head={["Service", "Metric", "Method", "Observed", "Expected ≤", "Score", "Confidence", "Detected"]}>
            {anomalies.data.map((a) => (
              <tr key={a.id} className="row">
                <td className="td text-muted">{a.service}</td>
                <td className="td">{a.metric_name}</td>
                <td className="td text-muted">{a.method}</td>
                <td className="td">{num(a.observed_value, 3)}</td>
                <td className="td text-muted">{num(a.expected_high, 3)}</td>
                <td className="td">{num(a.score, 2)}</td>
                <td className="td">{a.confidence.toFixed(2)}</td>
                <td className="td text-muted">{ago(a.detected_at)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
