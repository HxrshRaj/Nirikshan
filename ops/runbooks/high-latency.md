# Runbook: high latency / slow responses

1. **Measure.** `ops/diagnose.sh --http <url> --slow-ms 500` shows status and latency per endpoint.
2. **Narrow the layer.** Slow DNS (`--dns`), slow TCP connect (`--tcp` prints connect time) or slow application (HTTP slow but TCP fast).
3. **Check saturation.** `--mem --disk`; CPU with `top -bn1 | head -15`; open connections with `ss -s`.
4. **Check the database.** Long-running queries (`SELECT pid, now()-query_start, query FROM pg_stat_activity WHERE state <> 'idle' ORDER BY 2 DESC LIMIT 5;`), connection pool exhaustion, missing index after a deploy.
5. **Check queues and cache.** Redis memory and evictions (`redis-cli info memory`), growing queue depth.
6. **Mitigate.** Scale out, restart the stuck worker, disable the expensive feature, or roll back.
7. **Verify** latency is back under threshold, then document.
