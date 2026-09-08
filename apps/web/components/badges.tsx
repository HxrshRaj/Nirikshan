export function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    "SEV-1": "border-sev1/60 text-sev1 bg-sev1/10",
    "SEV-2": "border-sev2/60 text-sev2 bg-sev2/10",
    "SEV-3": "border-sev3/60 text-sev3 bg-sev3/10",
    "SEV-4": "border-sev4/60 text-sev4 bg-sev4/10",
  };
  return <span className={`pill ${map[severity] || map["SEV-4"]}`}>{severity}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "RESOLVED" || status === "CLOSED"
      ? "border-ok/50 text-ok bg-ok/10"
      : status === "MITIGATING" || status === "ACKNOWLEDGED"
        ? "border-warn/50 text-warn bg-warn/10"
        : "border-bad/50 text-bad bg-bad/10";
  return <span className={`pill ${tone}`}>{status}</span>;
}

export function HealthDot({ health }: { health: string }) {
  const c =
    health === "HEALTHY"
      ? "bg-ok"
      : health === "DEGRADED"
        ? "bg-warn"
        : health === "UNHEALTHY"
          ? "bg-bad"
          : "bg-muted";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${c}`} />
      <span className="text-xs text-muted">{health}</span>
    </span>
  );
}

export function MockBadge({ isMock }: { isMock: boolean | undefined }) {
  if (!isMock) return null;
  return (
    <span className="pill border-warn/50 bg-warn/10 text-warn" title="Deterministic demo reasoner, not a production model">
      DEMO / MOCK PROVIDER
    </span>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone =
    risk === "HIGH"
      ? "border-bad/50 text-bad bg-bad/10"
      : risk === "MEDIUM"
        ? "border-warn/50 text-warn bg-warn/10"
        : "border-ok/50 text-ok bg-ok/10";
  return <span className={`pill ${tone}`}>{risk}</span>;
}
