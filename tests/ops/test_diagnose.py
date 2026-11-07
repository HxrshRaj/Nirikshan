"""Tests for ops/diagnose.sh: run the script against real local sockets and files."""
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "diagnose.sh"


def run(*args):
    p = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = {"/ok": 200, "/missing": 404, "/boom": 500}.get(self.path, 200)
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_no_args_prints_usage():
    code, _ = run()
    assert code == 64


def test_unknown_option():
    code, _ = run("--bogus")
    assert code == 64


def test_help():
    code, out = run("--help")
    assert code == 0 and "Usage" in out


def test_tcp_open_passes(server):
    code, out = run("--tcp", f"127.0.0.1:{server}")
    assert code == 0 and out.startswith("PASS tcp")


def test_tcp_closed_fails():
    code, out = run("--tcp", f"127.0.0.1:{free_port()}")
    assert code == 2 and "FAIL tcp" in out


def test_tcp_bad_target():
    code, out = run("--tcp", "nonsense")
    assert code == 2 and "not HOST:PORT" in out


def test_http_200_passes(server):
    code, out = run("--http", f"http://127.0.0.1:{server}/ok")
    assert code == 0 and "PASS http" in out


def test_http_404_warns(server):
    code, out = run("--http", f"http://127.0.0.1:{server}/missing")
    assert code == 1 and "WARN http" in out


def test_http_500_fails(server):
    code, out = run("--http", f"http://127.0.0.1:{server}/boom")
    assert code == 2 and "FAIL http" in out


def test_http_no_listener_fails():
    code, out = run("--http", f"http://127.0.0.1:{free_port()}/", "--timeout", "2")
    assert code == 2 and "FAIL http" in out


def test_dns_localhost_resolves():
    code, out = run("--dns", "localhost")
    assert code == 0 and "PASS dns" in out


def test_dns_invalid_fails():
    code, out = run("--dns", "nope.invalid")
    assert code == 2 and "FAIL dns" in out


def test_log_clean_and_errors(tmp_path):
    clean = tmp_path / "clean.log"
    clean.write_text("INFO started\nINFO ok\n")
    bad = tmp_path / "bad.log"
    bad.write_text("INFO started\nERROR db connection refused\nTraceback (most recent call last)\n")
    code, out = run("--log", str(clean))
    assert code == 0 and "PASS log" in out
    code, out = run("--log", str(bad))
    assert code == 1 and "WARN log" in out and "2 error lines" in out


def test_log_missing_fails(tmp_path):
    code, out = run("--log", str(tmp_path / "nope.log"))
    assert code == 2 and "FAIL log" in out


def test_log_lines_window(tmp_path):
    f = tmp_path / "a.log"
    f.write_text("ERROR old\n" + "INFO fine\n" * 10)
    code, _ = run("--log", str(f), "--log-lines", "5")
    assert code == 0


def test_disk_and_mem_report_a_level():
    _, out = run("--disk", "/", "--mem")
    levels = [line.split()[0] for line in out.splitlines() if line.split()[0] in ("PASS", "WARN", "FAIL")]
    assert len(levels) == 2


def test_summary_counts(server):
    code, out = run("--tcp", f"127.0.0.1:{server}", "--tcp", f"127.0.0.1:{free_port()}")
    assert code == 2 and "SUMMARY pass=1 warn=0 fail=1" in out
