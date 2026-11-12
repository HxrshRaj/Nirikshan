"""Tests for ops/logstats.sh against small hand-written logs with known answers."""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "logstats.sh"

APP_LOG = """\
2026-11-05T10:15:03 INFO started
2026-11-05T10:15:10 ERROR db timeout after 31ms for order 1001
2026-11-05T10:15:40 ERROR db timeout after 52ms for order 1002
2026-11-05T10:15:59 WARNING slow query
2026-11-05T10:16:05 ERROR cache miss storm id=0xdeadbeef
2026-11-05T10:16:30 INFO ok
2026-11-05T10:16:31 ERROR db timeout after 77ms for order 1003
"""

ACCESS_LOG = """\
10.0.0.1 - - [05/Nov/2026:10:00:01 +0000] "GET /api/orders?page=1 HTTP/1.1" 200 512 "-" "curl"
10.0.0.1 - - [05/Nov/2026:10:00:02 +0000] "GET /api/orders?page=2 HTTP/1.1" 200 498 "-" "curl"
10.0.0.2 - - [05/Nov/2026:10:00:03 +0000] "POST /api/orders HTTP/1.1" 201 90 "-" "curl"
10.0.0.2 - - [05/Nov/2026:10:00:04 +0000] "GET /api/inventory HTTP/1.1" 500 10 "-" "curl"
10.0.0.3 - - [05/Nov/2026:10:00:05 +0000] "GET /missing HTTP/1.1" 404 10 "-" "curl"
"""


def run(args, stdin=None):
    p = subprocess.run(["bash", str(SCRIPT), *args], input=stdin, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


def test_app_log_levels_and_masked_top_errors(tmp_path):
    f = tmp_path / "app.log"
    f.write_text(APP_LOG)
    code, out, _ = run([str(f)])
    assert code == 0
    assert "7 lines" in out
    # 4 ERROR, 2 INFO, 1 WARN (WARNING is normalised)
    assert any(line.split()[:2] == ["4", "ERROR"] for line in out.splitlines())
    assert any(line.split()[:2] == ["2", "INFO"] for line in out.splitlines())
    assert any(line.split()[:2] == ["1", "WARN"] for line in out.splitlines())
    # three timeouts differ only by numbers, so they group into one message with count 3
    assert any(line.strip().startswith("3 ") and "db timeout after <n>ms for order <n>" in line for line in out.splitlines())
    assert "cache miss storm id=<hex>" in out


def test_errors_per_minute_busiest_first(tmp_path):
    f = tmp_path / "app.log"
    f.write_text(APP_LOG)
    _, out, _ = run([str(f)])
    section = out.split("errors per minute")[1].split("top")[0]
    lines = [ln.split() for ln in section.splitlines() if "2026-" in ln]
    assert lines[0] == ["2", "2026-11-05T10:15"] or lines[0] == ["2", "2026-11-05T10:16"]
    assert sum(int(x[0]) for x in lines) == 4


def test_access_log_summary(tmp_path):
    f = tmp_path / "access.log"
    f.write_text(ACCESS_LOG)
    code, out, _ = run(["--access", str(f)])
    assert code == 0
    assert "5 requests" in out
    assert "2xx  3" in out and "4xx  1" in out and "5xx  1" in out
    # query strings are stripped, so /api/orders counts 3 (two GETs and one POST)
    assert any(line.split()[:2] == ["3", "/api/orders"] for line in out.splitlines())
    assert "5xx responses: 1 of 5 (20.0%)" in out


def test_reads_stdin_and_top_limit():
    code, out, _ = run(["--access", "--top", "1", "-"], stdin=ACCESS_LOG)
    assert code == 0
    paths = out.split("top 1 paths")[1].split("top 1 client IPs")[0].strip().splitlines()
    paths = [ln for ln in paths if not ln.startswith("--")]
    assert paths == ["      3 /api/orders"] or [p.split() for p in paths] == [["3", "/api/orders"]]


def test_empty_input_and_errors(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    code, out, _ = run([str(empty)])
    assert code == 0 and "no input lines" in out
    code, _, err = run([str(tmp_path / "missing.log")])
    assert code == 66 and "cannot read" in err
    code, _, _ = run(["--bogus"])
    assert code == 64
    code, _, _ = run(["--top", "abc", str(empty)])
    assert code == 64


def test_help():
    code, out, _ = run(["--help"])
    assert code == 0 and "Usage" in out
