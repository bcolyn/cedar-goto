"""Generate Python gRPC stubs from cedar-server's .proto files.

Run with: .venv/Scripts/python scripts/generate_grpc_stubs.py

The .proto sources live in proto/ (pulled from smroid/cedar-server,
elements/src/proto/). Generated code lands in
src/cedar_goto/adapters/cedar_grpc/generated/ and is committed so a fresh
checkout doesn't need network access to build.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "src" / "cedar_goto" / "adapters" / "cedar_grpc" / "generated"

PROTO_FILES = ["cedar_common.proto", "cedar_sky.proto", "cedar.proto"]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    init_file = OUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    for proto_file in PROTO_FILES:
        cmd = [
            sys.executable, "-m", "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={OUT_DIR}",
            f"--grpc_python_out={OUT_DIR}",
            f"--pyi_out={OUT_DIR}",
            str(PROTO_DIR / proto_file),
        ]
        print("+", " ".join(cmd))
        subprocess.run(cmd, check=True)

    # grpc_tools generates imports like `import cedar_common_pb2 as ...` which
    # only resolve if the generated package is on sys.path directly. Rewrite
    # to package-relative imports so `cedar_goto.adapters.cedar_grpc.generated`
    # works as a normal importable package.
    for py_file in OUT_DIR.glob("*_pb2*.py"):
        text = py_file.read_text()
        patched = text
        for proto_file in PROTO_FILES:
            mod = proto_file.removesuffix(".proto")
            patched = patched.replace(f"import {mod}_pb2", f"from . import {mod}_pb2")
        if patched != text:
            py_file.write_text(patched)
            print("patched imports in", py_file.name)

    print(f"\nGenerated stubs in {OUT_DIR}")


if __name__ == "__main__":
    main()
