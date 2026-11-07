# Runbook: DNS and network connectivity

1. `ops/diagnose.sh --dns <name> --tcp <host>:<port>`.
2. **DNS FAIL:** check `/etc/resolv.conf`, try `getent hosts <name>` and `dig @8.8.8.8 <name>` to separate resolver issues from record issues. Check TTL if the record changed recently.
3. **DNS ok, TCP FAIL:** the port is closed (service down), filtered (firewall / security group / network policy) or routing is broken. `ss -ltnp` on the target shows whether it is listening; `traceroute <host>` shows where packets stop.
4. **TCP ok, HTTP FAIL:** TLS (`openssl s_client -connect host:443`, expired certificate), proxy or load balancer misconfiguration, wrong Host header.
5. Fix at the right layer, then verify with the same command.
