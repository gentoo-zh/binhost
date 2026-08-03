#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "check-copy.py"
spec = importlib.util.spec_from_file_location("check_copy", TARGET)
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

FIXTURES = json.loads((HERE / "copy-fixtures.json").read_text())
CASES = FIXTURES["cases"]
CLEAN = FIXTURES["clean"]


def run(tree):
    root = pathlib.Path(tree)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        n = cc.check_comments(root) + cc.check_emitted(root)
    return n, buf.getvalue()


def plant(tree, rel, body):
    p = pathlib.Path(tree) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


bad = 0
with tempfile.TemporaryDirectory() as base:
    for rel, body in CLEAN.items():
        plant(base, rel, body)
    n, out = run(base)
    if n:
        print(f"  ✗ 合规的样本被误报 {n} 处\n{out}")
        bad += 1
    else:
        print("  ✓ 合规的样本不报错")

for name, rel, body, _kind in CASES:
    with tempfile.TemporaryDirectory() as base:
        for r, b in CLEAN.items():
            plant(base, r, b)
        plant(base, rel, CLEAN.get(rel, "") + body)
        n, out = run(base)
        if n:
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}：样本含违规用词，检查器仍报通过")
            bad += 1

with tempfile.TemporaryDirectory() as base:
    site = pathlib.Path(base) / "site"
    site.mkdir()
    (site / "ok.html").write_text(FIXTURES["site"]["ok"])
    with contextlib.redirect_stdout(io.StringIO()):
        clean_rc = cc.main(str(site))
    if clean_rc == 0:
        print("  ✓ 站点正文用词正确时不报错")
    else:
        print("  ✗ 站点正文用词正确时被误报")
        bad += 1
    (site / "bad.html").write_text(FIXTURES["site"]["bad"])
    with contextlib.redirect_stdout(io.StringIO()):
        dirty_rc = cc.main(str(site))
    if dirty_rc != 0:
        print("  ✓ 站点正文里的违规用词会被检出")
    else:
        print("  ✗ 站点正文里的违规用词未被检出")
        bad += 1

if bad:
    print(f"\n>>> {bad} 项未通过")
    sys.exit(1)
print(f"\n  {len(CASES)} 种写法都能被检出")
