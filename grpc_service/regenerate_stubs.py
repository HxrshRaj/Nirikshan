#!/usr/bin/env python
"""Regenerate the Python gRPC stubs from service_health.proto.

Run this after editing the .proto file:

    python grpc_service/regenerate_stubs.py

Requires the `grpc` extra: pip install -e ".[grpc]"

The generated *_pb2_grpc.py imports its sibling *_pb2 module with a bare
`import x_pb2`, which only resolves when that directory is on sys.path
directly - not as the package `grpc_service.generated.x_pb2` this repo uses
everywhere else. This is a known limitation of protoc's Python plugin, not a
project quirk (https://github.com/protocolbuffers/protobuf/issues/1491). The
fix applied below - rewriting that one line to a package-relative import - is
the standard workaround; it is re-applied every time this script runs, so the
generated files always stay importable as `grpc_service.generated.*`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "generated"


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "__init__.py").touch(exist_ok=True)

    proto_files = sorted(PROTO_DIR.glob("*.proto"))
    if not proto_files:
        print(f"no .proto files found in {PROTO_DIR}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"--proto_path={PROTO_DIR}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        f"--pyi_out={OUT_DIR}",
        *[str(p) for p in proto_files],
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)

    for grpc_stub in OUT_DIR.glob("*_pb2_grpc.py"):
        text = grpc_stub.read_text(encoding="utf-8")
        patched = re.sub(
            r"^import (\w+_pb2) as (\S+)$",
            r"from . import \1 as \2",
            text,
            flags=re.MULTILINE,
        )
        if patched != text:
            grpc_stub.write_text(patched, encoding="utf-8")
            print(f"patched {grpc_stub.relative_to(ROOT)} to use a package-relative import")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
