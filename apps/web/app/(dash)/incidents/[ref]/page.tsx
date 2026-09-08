"use client";

import Link from "next/link";
import { use, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { time } from "@/lib/format";
import { Card, ConfidenceBar, Empty, ErrorBox, KV, Loading } from "@/components/ui";
import { MockBadge, RiskBadge, SeverityBadge, StatusBadge } from "@/components/badges";

interface Detail {
  ref: string;
  title: string;
  severity: string;
  status: string;
  service: string;
  detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  confidence: number | null;
  summary: string;
  root_cause: string;
  contributing_factors: string[];
  recommended_actions: string[];
  blast_radius: Record<string, unknown>;
  correlated_alert_refs: string[];
  events: { id: string; at: string; kind: string; message: string; actor: string; source: string }[];
  evidence: { id: string; kind: string; ref_id: string; summary: string; weight: number }[];
  hypotheses: {
    id: string;
    rank: number;
    title: string;
    category: string;
    rationale: string;
    confidence: number;
    supporting_evidence_ids: string[];
    is_selected: boolean;
  }[];
  last_investigation_run_id: string | null;
}

export default function IncidentDetailPage({ params }: { params: Promise<{ ref: string }> }) {
  const { ref } = use(params);
  const { data, error, loading, reload } = useApi<Detail>(`/api/incidents/${ref}`);
  const rem = useApi<{ id: string; ref: string; incident_id: string }[]>(`/api/remediations`);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>, label: string) {
    setBusy(label);
    setMsg(null);
    try {
      await fn();
      await reload();
      await rem.reload();
      setMsg(`${label} ok`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(null);
    }
  }

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox message={error.message} />;
  if (!data) return <Empty>Not found</Empty>;

  const myRem = (rem.data || []).filter((r) => r.incident_id);
  const bad = data.blast_radius as {
    direct_dependents?: string[];
    indirect_dependents?: string[];
    impacted_user_facing?: string[];
    total_impacted?: number;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <SeverityBadge severity={data.severity} />
        <StatusBadge status={data.status} />
        <h1 className="text-lg font-semibold">{data.title}</h1>
        <span className="font-mono text-sm text-muted">{data.ref}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <button className="btn" disabled={!!busy} onClick={() => act(() => api.post(`/api/incidents/${ref}/acknowledge`, { note: "ack from UI" }), "acknowledge")}>
          Acknowledge
        </button>
        <button className="btn" disabled={!!busy} onClick={() => act(() => api.post(`/api/incidents/${ref}/investigate`, { force: true }), "re-investigate")}>
          Re-investigate
        </button>
        <button className="btn" disabled={!!busy} onClick={() => act(() => api.post(`/api/incidents/${ref}/remediation`, { force: true }), "propose remediation")}>
          Propose remediation
        </button>
        <button className="btn" disabled={!!busy} onClick={() => act(() => api.post(`/api/incidents/${ref}/resolve`, { resolution: "resolved from UI" }), "resolve")}>
          Resolve
        </button>
        {busy && <span className="text-xs text-muted">{busy}…</span>}
        {msg && <span className="text-xs text-accent">{msg}</span>}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Summary" className="lg:col-span-2">
          <div className="kv">
            <KV k="Service">{data.service}</KV>
            <KV k="Detected">{time(data.detected_at)}</KV>
            <KV k="Acknowledged">{time(data.acknowledged_at)}</KV>
            <KV k="Resolved">{time(data.resolved_at)}</KV>
            <KV k="Correlated alerts">{data.correlated_alert_refs.join(", ") || "—"}</KV>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm text-muted">{data.summary}</p>
        </Card>

        <Card title="Blast radius">
          <div className="kv text-sm">
            <KV k="Direct">{bad.direct_dependents?.join(", ") || "—"}</KV>
            <KV k="Indirect">{bad.indirect_dependents?.join(", ") || "—"}</KV>
            <KV k="User-facing">{bad.impacted_user_facing?.join(", ") || "—"}</KV>
            <KV k="Total impacted">{bad.total_impacted ?? 0}</KV>
          </div>
        </Card>
      </div>

      <Card
        title={
          <span className="flex items-center gap-2">
            Root Cause Analysis
            {data.last_investigation_run_id && (
              <Link href={`/investigations/${data.last_investigation_run_id}`} className="text-xs text-accent">
                view run →
              </Link>
            )}
          </span>
        }
      >
        <div className="mb-3 flex items-center gap-3">
          <span className="text-sm font-semibold">{data.root_cause || "not yet determined"}</span>
          <ConfidenceBar value={data.confidence} />
        </div>
        {data.contributing_factors.length > 0 && (
          <div className="mb-3 text-sm">
            <div className="text-xs uppercase text-muted">Contributing factors</div>
            <ul className="ml-4 list-disc text-muted">
              {data.contributing_factors.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {data.recommended_actions.length > 0 && (
          <div className="text-sm">
            <div className="text-xs uppercase text-muted">Recommended actions</div>
            <ul className="ml-4 list-disc text-muted">
              {data.recommended_actions.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Hypotheses (ranked)">
          {data.hypotheses.length === 0 ? (
            <Empty>No hypotheses yet.</Empty>
          ) : (
            <div className="space-y-3">
              {data.hypotheses.map((h) => (
                <div key={h.id} className={`rounded-md border p-3 ${h.is_selected ? "border-accent/60 bg-accent/5" : "border-border"}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">
                      {h.rank}. {h.title}
                    </span>
                    <ConfidenceBar value={h.confidence} />
                  </div>
                  <div className="mt-1 text-xs text-muted">{h.category}</div>
                  <p className="mt-1 text-xs text-muted">{h.rationale}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {h.supporting_evidence_ids.map((e) => (
                      <span key={e} className="pill border-border text-muted">
                        {e}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Evidence">
          {data.evidence.length === 0 ? (
            <Empty>No evidence collected.</Empty>
          ) : (
            <div className="space-y-2">
              {data.evidence.map((e) => (
                <div key={e.id} className="row rounded-md px-2 py-2">
                  <div className="flex items-center justify-between">
                    <span className="pill border-border text-muted">{e.kind}</span>
                    <span className="text-xs text-muted">weight {e.weight}</span>
                  </div>
                  <div className="mt-1 text-sm text-muted">{e.summary}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Timeline">
        <ol className="relative ml-3 border-l border-border">
          {data.events.map((ev) => (
            <li key={ev.id} className="mb-3 ml-4">
              <span className="absolute -left-1.5 mt-1 h-3 w-3 rounded-full border border-border bg-panel2" />
              <div className="text-xs text-muted">{time(ev.at)} · {ev.source}</div>
              <div className="text-sm">{ev.message}</div>
            </li>
          ))}
        </ol>
      </Card>

      {myRem.length > 0 && (
        <Card title="Remediations">
          {myRem.map((r) => (
            <RemediationRow key={r.ref} refId={r.ref} onChange={() => { reload(); rem.reload(); }} />
          ))}
        </Card>
      )}
    </div>
  );
}

function RemediationRow({ refId, onChange }: { refId: string; onChange: () => void }) {
  const { data, reload } = useApi<{
    ref: string;
    action_name: string;
    parameters: Record<string, unknown>;
    rationale: string;
    risk: string;
    status: string;
    expected_impact: string;
    rollback_plan: string;
    verification_plan: Record<string, unknown>;
    is_mock?: boolean;
    executions: { verification: Record<string, unknown> }[];
  }>(`/api/remediations/${refId}`);
  const [busy, setBusy] = useState<string | null>(null);
  if (!data) return null;

  async function act(path: string, label: string) {
    setBusy(label);
    try {
      await api.post(path, { reason: `${label} from UI` });
      await reload();
      onChange();
    } finally {
      setBusy(null);
    }
  }

  const lastVerification = data.executions.at(-1)?.verification as
    | { summary?: string; success?: boolean }
    | undefined;

  return (
    <div className="mb-3 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-accent">{data.ref}</span>
        <span className="text-sm font-medium">{data.action_name}</span>
        <RiskBadge risk={data.risk} />
        <span className="pill border-border text-muted">{data.status}</span>
        <MockBadge isMock={data.is_mock} />
      </div>
      <p className="mt-1 text-xs text-muted">{data.rationale}</p>
      <div className="mt-1 text-xs text-muted">
        <b>Params:</b> {JSON.stringify(data.parameters)} · <b>Impact:</b> {data.expected_impact}
      </div>
      <div className="mt-1 text-xs text-muted">
        <b>Rollback:</b> {data.rollback_plan}
      </div>
      {lastVerification && (
        <div className={`mt-1 text-xs ${lastVerification.success ? "text-ok" : "text-warn"}`}>
          Verification: {lastVerification.summary}
        </div>
      )}
      <div className="mt-2 flex gap-2">
        {(data.status === "APPROVAL_REQUIRED" || data.status === "PROPOSED") && (
          <>
            <button className="btn btn-primary" disabled={!!busy} onClick={() => act(`/api/remediations/${data.ref}/approve`, "approve")}>
              Approve &amp; execute
            </button>
            <button className="btn btn-danger" disabled={!!busy} onClick={() => act(`/api/remediations/${data.ref}/reject`, "reject")}>
              Reject
            </button>
          </>
        )}
        {(data.status === "VERIFYING" || data.status === "EXECUTING") && (
          <button className="btn" disabled={!!busy} onClick={() => act(`/api/remediations/${data.ref}/verify`, "verify")}>
            Verify
          </button>
        )}
        {(data.status === "SUCCEEDED" || data.status === "FAILED") && (
          <button className="btn" disabled={!!busy} onClick={() => act(`/api/remediations/${data.ref}/rollback`, "rollback")}>
            Rollback
          </button>
        )}
        {busy && <span className="text-xs text-muted">{busy}…</span>}
      </div>
    </div>
  );
}
