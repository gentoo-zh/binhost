#!/usr/bin/env python3
"""Check kernel archive Manifest parsing and payload verification."""

import hashlib
import importlib.util
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "kernel-manifest.py"
spec = importlib.util.spec_from_file_location("kernel_manifest", SCRIPT)
km = importlib.util.module_from_spec(spec)
spec.loader.exec_module(km)

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def rejects(name, call):
    try:
        call()
    except km.ManifestError:
        check(name, True)
    else:
        check(name, False, "没有拒绝无效输入")


with tempfile.TemporaryDirectory() as raw:
    work = pathlib.Path(raw)
    payload = work / "demo.gpkg.tar"
    payload.write_bytes(b"kernel archive\n")
    data = payload.read_bytes()
    sha512 = hashlib.sha512(data).hexdigest()
    blake2b = hashlib.blake2b(data).hexdigest()
    manifest = work / "Manifest"
    manifest.write_text(
        f"DIST {payload.name} {len(data)} BLAKE2B {blake2b} SHA512 {sha512}\n",
        encoding="utf-8",
    )

    check("读取 Manifest 中的大小与 SHA512",
          km.manifest_entry(manifest, payload.name) ==
          (len(data), "SHA512", sha512))
    km.verify_file(manifest, payload.name, payload)
    check("大小与摘要都相符时通过", True)

    payload.write_bytes(data + b"broken")
    rejects("大小不符时拒绝", lambda: km.verify_file(manifest, payload.name, payload))
    same_size = b"x" * len(data)
    payload.write_bytes(same_size)
    rejects("大小相同但摘要不符时拒绝",
            lambda: km.verify_file(manifest, payload.name, payload))
    rejects("Manifest 没有对应条目时拒绝",
            lambda: km.manifest_entry(manifest, "missing.gpkg.tar"))

print()
print("  内核 Manifest：全部通过" if not failed else f"  {failed} 项不通过")
raise SystemExit(1 if failed else 0)
