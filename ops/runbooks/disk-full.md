# Runbook: disk full

1. `ops/diagnose.sh --disk /` (and `--disk /var`). FAIL at 95% or more.
2. Find the cause: `du -xh / --max-depth=2 2>/dev/null | sort -rh | head -15`.
3. Usual suspects: runaway logs (`/var/log`), Docker layers (`docker system df`), core dumps, old backups.
4. Safe cleanup: rotate or compress logs (`logrotate -f /etc/logrotate.conf`), `docker image prune`, remove files you can account for. Never delete database files or the WAL by hand.
5. If the app wrote the files, fix the source (log level, rotation) so it does not recur.
6. Verify disk below 80%, confirm the service recovered with `ops/diagnose.sh --http <url>`.
