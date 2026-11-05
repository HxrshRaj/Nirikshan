#!/usr/bin/env bash
# First-line diagnostics for a service: DNS, TCP ports, HTTP status and latency, log errors, disk, memory, containers.
# Read-only: it never changes anything on the host.
#
# Examples:
#   ops/diagnose.sh --dns api.example.com --tcp api.example.com:443 --http https://api.example.com/health
#   ops/diagnose.sh --tcp localhost:5432 --log /var/log/app/app.log --disk /var --mem --docker
#
# Exit code: 0 = everything passed, 1 = warnings, 2 = at least one failure.
# Output:    one line per check, "PASS|WARN|FAIL <check> <detail>", then a summary line.

set -u

TIMEOUT=3
SLOW_MS=1000
LOG_LINES=500
DISK_PATH="/"
DISK_WARN=80
DISK_FAIL=95
DNS_NAMES=(); TCP_TARGETS=(); HTTP_URLS=(); LOG_FILES=()
CHECK_MEM=0; CHECK_DOCKER=0
PASS=0; WARN=0; FAIL=0

usage() {
  cat <<'USAGE'
Usage: diagnose.sh [options]
  --dns NAME          check that NAME resolves (repeatable)
  --tcp HOST:PORT     check that a TCP port accepts connections (repeatable)
  --http URL          check HTTP status and latency (repeatable); 5xx or timeout = FAIL, 4xx or slow = WARN
  --log FILE          count ERROR/FATAL/Traceback/OutOfMemory lines in the last N lines of FILE (repeatable)
  --disk PATH         check disk usage of PATH (default /); WARN >= 80%, FAIL >= 95%
  --mem               check available memory (WARN < 15%, FAIL < 5%)
  --docker            list containers that are restarting, exited or unhealthy
  --timeout SECONDS   per-check timeout (default 3)
  --slow-ms MS        latency above this is a WARN (default 1000)
  --log-lines N       how many trailing log lines to scan (default 500)
  -h, --help          show this help
USAGE
}

report() { # level check detail
  case "$1" in PASS) PASS=$((PASS+1));; WARN) WARN=$((WARN+1));; FAIL) FAIL=$((FAIL+1));; esac
  printf '%-4s %-10s %s\n' "$1" "$2" "$3"
}

check_dns() {
  local name="$1" out=""
  if command -v getent >/dev/null 2>&1; then
    out=$(timeout "$TIMEOUT" getent hosts "$name" 2>/dev/null | awk 'NR==1{print $1}')
  elif command -v host >/dev/null 2>&1; then
    out=$(timeout "$TIMEOUT" host "$name" 2>/dev/null | awk '/has address/{print $NF; exit}')
  fi
  if [ -n "$out" ]; then report PASS dns "$name -> $out"
  else report FAIL dns "$name did not resolve (check /etc/resolv.conf, the record, and the resolver)"; fi
}

check_tcp() {
  local target="$1" host port
  host="${target%:*}"; port="${target##*:}"
  if ! [[ "$port" =~ ^[0-9]+$ ]] || [ -z "$host" ] || [ "$host" = "$target" ]; then
    report FAIL tcp "'$target' is not HOST:PORT"; return
  fi
  local start end ms
  start=$(date +%s%3N)
  if timeout "$TIMEOUT" bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
    end=$(date +%s%3N); ms=$((end-start))
    report PASS tcp "$host:$port open (${ms} ms)"
  else
    report FAIL tcp "$host:$port refused or timed out (service down, wrong port, or a firewall is dropping it)"
  fi
}

check_http() {
  local url="$1" out code secs ms
  if ! command -v curl >/dev/null 2>&1; then report WARN http "curl not installed, skipped $url"; return; fi
  out=$(curl -s -o /dev/null --max-time "$TIMEOUT" -w '%{http_code} %{time_total}' "$url" 2>/dev/null) || true
  code="${out%% *}"; secs="${out##* }"
  if [ -z "$out" ] || [ "$code" = "000" ]; then
    report FAIL http "$url no response within ${TIMEOUT}s (DNS, connect, TLS or timeout)"; return
  fi
  ms=$(awk -v s="$secs" 'BEGIN{printf "%d", s*1000}')
  if [ "$code" -ge 500 ]; then report FAIL http "$url -> $code (${ms} ms), server-side error"
  elif [ "$code" -ge 400 ]; then report WARN http "$url -> $code (${ms} ms), client error (auth, path or payload)"
  elif [ "$ms" -gt "$SLOW_MS" ]; then report WARN http "$url -> $code but slow (${ms} ms > ${SLOW_MS} ms)"
  else report PASS http "$url -> $code (${ms} ms)"; fi
}

check_log() {
  local file="$1" n
  if [ ! -r "$file" ]; then report FAIL log "$file missing or not readable"; return; fi
  n=$(tail -n "$LOG_LINES" "$file" | grep -Eci 'error|fatal|traceback|out ?of ?memory|oom')
  if [ "$n" -eq 0 ]; then report PASS log "$file: no errors in last $LOG_LINES lines"
  else
    report WARN log "$file: $n error lines in last $LOG_LINES lines; latest: $(tail -n "$LOG_LINES" "$file" | grep -Ei 'error|fatal|traceback|out ?of ?memory|oom' | tail -n 1 | cut -c1-120)"
  fi
}

check_disk() {
  local pct
  pct=$(df -P "$DISK_PATH" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')
  if [ -z "$pct" ]; then report FAIL disk "cannot read $DISK_PATH"; return; fi
  if [ "$pct" -ge "$DISK_FAIL" ]; then report FAIL disk "$DISK_PATH at ${pct}% (full: find large files, rotate logs)"
  elif [ "$pct" -ge "$DISK_WARN" ]; then report WARN disk "$DISK_PATH at ${pct}%"
  else report PASS disk "$DISK_PATH at ${pct}%"; fi
}

check_mem() {
  local total avail pct
  total=$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)
  avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
  if [ -z "$total" ] || [ -z "$avail" ]; then report WARN mem "/proc/meminfo not available"; return; fi
  pct=$((avail*100/total))
  if [ "$pct" -lt 5 ]; then report FAIL mem "only ${pct}% available (check for a leak or an OOM-killed process)"
  elif [ "$pct" -lt 15 ]; then report WARN mem "${pct}% available"
  else report PASS mem "${pct}% available"; fi
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then report WARN docker "docker not installed, skipped"; return; fi
  local bad
  bad=$(timeout "$TIMEOUT" docker ps -a --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -Ei 'restarting|exited \([1-9]|unhealthy' || true)
  if [ -z "$bad" ]; then report PASS docker "no restarting, failed or unhealthy containers"
  else while IFS= read -r line; do report FAIL docker "$line"; done <<<"$bad"; fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dns) DNS_NAMES+=("${2:-}"); shift 2;;
    --tcp) TCP_TARGETS+=("${2:-}"); shift 2;;
    --http) HTTP_URLS+=("${2:-}"); shift 2;;
    --log) LOG_FILES+=("${2:-}"); shift 2;;
    --disk) DISK_PATH="${2:-/}"; CHECK_DISK=1; shift 2;;
    --mem) CHECK_MEM=1; shift;;
    --docker) CHECK_DOCKER=1; shift;;
    --timeout) TIMEOUT="${2:-3}"; shift 2;;
    --slow-ms) SLOW_MS="${2:-1000}"; shift 2;;
    --log-lines) LOG_LINES="${2:-500}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 64;;
  esac
done

CHECK_DISK=${CHECK_DISK:-0}
if [ ${#DNS_NAMES[@]} -eq 0 ] && [ ${#TCP_TARGETS[@]} -eq 0 ] && [ ${#HTTP_URLS[@]} -eq 0 ] \
   && [ ${#LOG_FILES[@]} -eq 0 ] && [ "$CHECK_DISK" -eq 0 ] && [ "$CHECK_MEM" -eq 0 ] && [ "$CHECK_DOCKER" -eq 0 ]; then
  usage >&2; exit 64
fi

for n in "${DNS_NAMES[@]+"${DNS_NAMES[@]}"}"; do check_dns "$n"; done
for t in "${TCP_TARGETS[@]+"${TCP_TARGETS[@]}"}"; do check_tcp "$t"; done
for u in "${HTTP_URLS[@]+"${HTTP_URLS[@]}"}"; do check_http "$u"; done
for f in "${LOG_FILES[@]+"${LOG_FILES[@]}"}"; do check_log "$f"; done
[ "$CHECK_DISK" -eq 1 ] && check_disk
[ "$CHECK_MEM" -eq 1 ] && check_mem
[ "$CHECK_DOCKER" -eq 1 ] && check_docker

echo "SUMMARY pass=$PASS warn=$WARN fail=$FAIL"
if [ "$FAIL" -gt 0 ]; then exit 2; elif [ "$WARN" -gt 0 ]; then exit 1; else exit 0; fi
