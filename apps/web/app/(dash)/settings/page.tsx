"use client";

import { useState } from "react";
import { api, getUser } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Card, Empty, JsonBlock, KV } from "@/components/ui";

interface Scenario {
  key: string;
  title: string;
  description: string;
  expected_category: string;
  expected_service: string;
}

export default function SettingsPage() {
  const user = getUser();
  const scenarios = useApi<Scenario[]>("/api/demo/scenarios");
  const actions = useApi<
    { name: string; description: string; default_risk: string; reversible: boolean; requires_role: string }[]
  >("/api/remediations/actions");
  const [busy, setBusy] = useState<string | null>(null);
  const [out, setOut] = useState<unknown>(null);
  const isAdmin = user?.role === "ADMIN";
  const isCommander = user?.role === "ADMIN" || user?.role === "INCIDENT_COMMANDER";

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setOut(null);
    try {
      setOut(await fn());
    } catch (e) {
      setOut({ error: e instanceof Error ? e.message : "failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Session">
        <div className="kv">
          <KV k="User">{user?.email}</KV>
          <KV k="Role">{user?.role}</KV>
        </div>
      </Card>

      <Card title="Demo control">
        {!isAdmin ? (
          <Empty>Seeding &amp; scenario runs require the ADMIN role.</Empty>
        ) : (
          <div className="space-y-3">
            <button
              className="btn btn-primary"
              disabled={!!busy}
              onClick={() => run("seed", () => api.post("/api/demo/seed"))}
            >
              Seed demo environment
            </button>
            <div className="grid gap-2 md:grid-cols-2">
              {(scenarios.data || []).map((s) => (
                <div key={s.key} className="rounded-md border border-border p-3">
                  <div className="text-sm font-medium">{s.title}</div>
                  <div className="text-xs text-muted">{s.description}</div>
                  <div className="mt-1 text-xs text-muted">
                    expects: {s.expected_category} on {s.expected_service || "—"}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      className="btn"
                      disabled={!!busy}
                      onClick={() =>
                        run(`scenario ${s.key}`, () =>
                          api.post("/api/demo/run-scenario", {
                            scenario: s.key,
                            investigate: true,
                            propose_remediation: true,
                          })
                        )
                      }
                    >
                      Run
                    </button>
                    {isCommander && s.key !== "normal" && (
                      <button
                        className="btn"
                        disabled={!!busy}
                        onClick={() =>
                          run(`scenario+remediate ${s.key}`, async () => {
                            const r = (await api.post("/api/demo/run-scenario", {
                              scenario: s.key,
                              investigate: true,
                              propose_remediation: true,
                            })) as { incident_ref: string };
                            return api.post("/api/demo/drive-remediation", {
                              incident_ref: r.incident_ref,
                              scenario: s.key,
                            });
                          })
                        }
                      >
                        Run + auto-remediate
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {busy && <div className="text-xs text-muted">{busy}…</div>}
            {out ? <JsonBlock data={out} /> : null}
          </div>
        )}
      </Card>

      <Card title="Remediation action allowlist">
        <p className="mb-2 text-xs text-muted">
          The AI can only request one of these registered actions with typed parameters — there is no
          path from model output to a shell command.
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          {(actions.data || []).map((a) => (
            <div key={a.name} className="rounded-md border border-border p-3 text-sm">
              <div className="font-mono text-xs text-accent">{a.name}</div>
              <div className="text-xs text-muted">{a.description}</div>
              <div className="mt-1 text-xs text-muted">
                risk {a.default_risk} · {a.reversible ? "reversible" : "non-reversible"} · needs {a.requires_role}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
