# Escalation guide

| Severity | Definition | First response | Escalate if not mitigated in |
|----------|------------|----------------|------------------------------|
| SEV1 | Full outage or data loss risk | Immediately | 15 min |
| SEV2 | Major feature degraded, workaround exists | 30 min | 1 hour |
| SEV3 | Minor issue, low user impact | Next business day | 1 day |

Escalate to the next tier when you are stuck, out of runbook steps, or the SLA above is at risk. When handing over, include: what is broken, what you checked (paste `ops/diagnose.sh` output), what you tried, and the current state. Keep a timeline in `ops/INCIDENT_TEMPLATE.md` format as you go.
