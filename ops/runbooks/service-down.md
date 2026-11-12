# Runbook: service down or returning 5xx

**Symptom:** health check fails, users see 5xx or timeouts. **Severity guide:** all users affected = SEV1, partial = SEV2.

1. **Confirm and scope.** `ops/diagnose.sh --http <health-url> --tcp <host>:<port>`. FAIL on tcp means the process or network is down; 5xx on http means the process is up but unhealthy.
2. **Check recent change.** Last deploy, config change or migration? If yes and the timing matches, roll back first and investigate after.
3. **Check the process.** `docker ps -a` / `systemctl status <svc>` / `kubectl get pods`. Restarting or exited containers: read the last 100 log lines (`docker logs --tail 100 <name>`).
4. **Check dependencies.** `ops/diagnose.sh --tcp <db-host>:5432 --tcp <redis-host>:6379`. A dead database or Redis explains most 5xx waves.
5. **Find the error pattern.** `ops/logstats.sh /var/log/app/app.log` groups the most repeated errors and shows which minute they spiked, which usually points at the first failure.
6. **Check resources.** `ops/diagnose.sh --disk / --mem`. Full disk or exhausted memory (OOM kill) are common root causes.
7. **Mitigate.** Restart the failing unit, roll back, or scale out. Record the time of each action.
8. **Verify.** Re-run step 1 until all checks PASS for 5 minutes.
9. **Close out.** Fill `ops/INCIDENT_TEMPLATE.md`. Escalate per `ops/ESCALATION.md` if not mitigated within the SLA.
