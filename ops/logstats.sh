#!/usr/bin/env bash
# Summarise an application or web-server log using standard Unix tools (awk, grep, sort, uniq).
# Read-only. Reads FILE, or stdin if FILE is "-" or omitted.
#
#   ops/logstats.sh app.log                 # app log: "<ISO timestamp> LEVEL message"
#   ops/logstats.sh --access access.log     # nginx/Apache combined access log
#   ops/logstats.sh --top 5 app.log
#   journalctl -u app --since today | ops/logstats.sh -
#
# App-log report: lines by level, errors per minute (busiest 5), top repeated error messages
# (numbers, hex ids and UUIDs are masked so "timeout after 31ms" and "timeout after 52ms" group together).
# Access-log report: requests by status class, top paths, top client IPs, 5xx count and rate.
set -u

TOP=10
MODE=app
FILE="-"

usage() {
  cat <<'USAGE'
Usage: logstats.sh [--access] [--top N] [FILE|-]
  --access   treat input as a combined-format web access log
  --top N    rows in each "top" table (default 10)
  -h, --help show this help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --access) MODE=access; shift;;
    --top) TOP="${2:-10}"; shift 2;;
    -h|--help) usage; exit 0;;
    -) FILE="-"; shift;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 64;;
    *) FILE="$1"; shift;;
  esac
done

case "$TOP" in ''|*[!0-9]*) echo "--top needs a number" >&2; exit 64;; esac
if [ "$FILE" != "-" ] && [ ! -r "$FILE" ]; then echo "cannot read $FILE" >&2; exit 66; fi

TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT
cat -- "$FILE" > "$TMP" 2>/dev/null || cat > "$TMP"
TOTAL=$(wc -l < "$TMP" | tr -d ' ')
if [ "$TOTAL" -eq 0 ]; then echo "no input lines"; exit 0; fi

if [ "$MODE" = "access" ]; then
  echo "== Access log: $TOTAL requests =="
  echo "-- by status class"
  awk '{ c=substr($9,1,1); if (c ~ /[1-5]/) n[c "xx"]++ } END { for (k in n) printf "%-4s %d\n", k, n[k] }' "$TMP" | sort
  echo "-- top $TOP paths"
  awk '{ split($7, p, "?"); print p[1] }' "$TMP" | sort | uniq -c | sort -rn | head -n "$TOP"
  echo "-- top $TOP client IPs"
  awk '{ print $1 }' "$TMP" | sort | uniq -c | sort -rn | head -n "$TOP"
  awk '$9 ~ /^5/ { e++ } END { printf "-- 5xx responses: %d of %d (%.1f%%)\n", e+0, NR, (e+0)*100/NR }' "$TMP"
else
  echo "== App log: $TOTAL lines =="
  echo "-- lines by level"
  grep -Eo '\b(DEBUG|INFO|WARN(ING)?|ERROR|CRITICAL|FATAL)\b' "$TMP" | sed 's/WARNING/WARN/' | sort | uniq -c | sort -rn
  echo "-- errors per minute (busiest 5)"
  grep -E '\b(ERROR|CRITICAL|FATAL)\b' "$TMP" | grep -Eo '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}' | sort | uniq -c | sort -rn | head -n 5
  echo "-- top $TOP repeated error messages"
  grep -E '\b(ERROR|CRITICAL|FATAL)\b' "$TMP" \
    | sed -E 's/^[^ ]+ +[^ ]* *//; s/\b(ERROR|CRITICAL|FATAL)\b:? *//' \
    | sed -E 's/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/<uuid>/g; s/0x[0-9a-fA-F]+/<hex>/g; s/[0-9]+/<n>/g' \
    | sort | uniq -c | sort -rn | head -n "$TOP"
fi
