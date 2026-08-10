#!/usr/bin/env python3
"""The rewritten index has to be a usable index, not just a shorter file.

publish.sh feeds prune-index.py a copy of what is currently published and then
switches to the result, so anything wrong here is wrong on the public path: a
count that no longer matches, a Packages.gz that disagrees with Packages, or a
generation.json that daily.sh will report as a mismatched generation.
"""

import gzip
import importlib.util
import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRUNE = ROOT / "build" / "prune-index.py"

spec = importlib.util.spec_from_file_location("prune_index", PRUNE)
prune_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune_index)

HEADER = ("ACCEPT_KEYWORDS: amd64\n"
          "ARCH: amd64\n"
          "PACKAGES: 3\n"
          "TIMESTAMP: 1700000000\n"
          "VERSION: 0")

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def stanza(cp, path):
    return (f"CPV: {cp}\n"
            f"PATH: {path}\n"
            "REPO: gentoo-zh\n"
            "SIZE: 7\n"
            "SLOT: 0")


PATHS = ["app-misc/a-1.gpkg.tar", "app-misc/b-1.gpkg.tar", "dev-libs/c-1.gpkg.tar"]


def published(directory):
    """A complete generation, the way publish.sh finds one on the mirror."""
    d = pathlib.Path(directory)
    body = "\n\n".join(stanza(f"x/y{i}-1", p) for i, p in enumerate(PATHS))
    text = HEADER + "\n\n" + body + "\n"
    (d / "Packages").write_text(text)
    (d / "Packages.gz").write_bytes(gzip.compress(text.encode()))
    for name in ("installed.txt", "official.txt", "source.txt"):
        (d / name).write_text(name + "\n")
    generation = importlib.util.spec_from_file_location(
        "generation", ROOT / "build" / "generation.py")
    module = importlib.util.module_from_spec(generation)
    generation.loader.exec_module(module)
    module.create(d)
    return module


def snapshot(d):
    return {f.name: (f.read_bytes(), f.stat().st_mtime_ns)
            for f in sorted(d.iterdir()) if f.is_file()}


def run(denied):
    """Drive the file the way publish.sh does, through its command line."""
    tmp = tempfile.TemporaryDirectory()
    d = pathlib.Path(tmp.name)
    module = published(d)
    deny = d / "deny.txt"
    deny.write_text("".join(x + "\n" for x in denied))
    # Content and mtime: a rewrite that happens to produce the same bytes is
    # still a write, and the point of the zero case is not writing at all.
    before = snapshot(d)
    p = subprocess.run([sys.executable, str(PRUNE), str(d), str(deny)],
                       capture_output=True, text=True)
    return tmp, d, module, p, before


print(">>> 移除一条")
tmp, d, generation, p, before = run([PATHS[1]])
text = (d / "Packages").read_text()
check("退出码为零", p.returncode == 0, p.stderr)
check("报出移除了几条", p.stdout.strip() == "1", p.stdout)
check("被点名的不在了", PATHS[1] not in text)
check("其余两条都保留", all(x in text for x in (PATHS[0], PATHS[2])))
check("头部数量改成 2",
      re.search(r"^PACKAGES: (\d+)$", text, re.M).group(1) == "2")
check("头部其余字段没动", "TIMESTAMP: 1700000000" in text and "ARCH: amd64" in text)
check("Packages.gz 与 Packages 一致",
      gzip.decompress((d / "Packages.gz").read_bytes()).decode() == text)

stanzas = [s for s in text.partition("\n\n")[2].split("\n\n") if s.strip()]
check("剩下的两条各自完整", len(stanzas) == 2 and
      all(s.startswith("CPV: ") and s.rstrip().endswith("SLOT: 0") for s in stanzas),
      repr(stanzas))
try:
    data = generation.verify(d)
    check("generation.json 重新生成且能通过校验", True)
except ValueError as error:
    check("generation.json 重新生成且能通过校验", False, str(error))
check("清单里仍是五个档案",
      set(json.loads((d / "generation.json").read_text())["files"]) ==
      set(generation.FILES))
tmp.cleanup()

print()
print(">>> 没有一条对得上时不改写")
tmp, d, generation, p, before = run(["app-misc/never-there.gpkg.tar"])
after = snapshot(d)
check("报出零条", p.stdout.strip() == "0", p.stdout)
check("退出码为零", p.returncode == 0)
check("一个字节都没动", after == before,
      " ".join(n for n in after if after[n] != before.get(n)))
tmp.cleanup()

print()
print(">>> 会清空索引时拒绝改写")
tmp, d, generation, p, before = run(PATHS)
check("退出码非零", p.returncode != 0)
check("说明原因", "不含任何软件包" in p.stderr, p.stderr)
check("原来的索引一个字节都没动", snapshot(d) == before)
try:
    generation.verify(d)
    check("原来的同代清单仍然成立", True)
except ValueError as error:
    check("原来的同代清单仍然成立", False, str(error))
tmp.cleanup()

print()
print(">>> 索引形状不对时不猜")
with tempfile.TemporaryDirectory() as raw:
    d = pathlib.Path(raw)
    (d / "Packages").write_text("PACKAGES: 1\n")
    (d / "deny.txt").write_text(PATHS[0] + "\n")
    p = subprocess.run([sys.executable, str(PRUNE), str(d), str(d / "deny.txt")],
                       capture_output=True, text=True)
    check("没有空行分隔时退出码非零", p.returncode != 0)
    check("说明原因", "空行" in p.stderr, p.stderr)

print()
print(">>> publish.sh 按这个形状使用它")
publish = (ROOT / "build" / "publish.sh").read_text()
start = "\nif [[ -s ${QUARANTINE} ]]; then\n"
end = "\nif [[ -s ${STAGE}/publish-blocked.txt ]]; then\n"
if start not in publish or end not in publish:
    check("读到隔离发布区块", False)
else:
    block = publish.split(start, 1)[1].split(end, 1)[0]
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        stage = root / "stage"
        stage.mkdir()
        quarantine = stage / "quarantine.txt"
        quarantine.write_text(PATHS[1] + "\n")
        events = root / "events"
        harness = f"""\
set -euo pipefail
STAGE={shlex.quote(str(stage))}
QUARANTINE={shlex.quote(str(quarantine))}
EVENTS={shlex.quote(str(events))}
REMOTE=test
REMOTE_ROOT={shlex.quote(str(root / "public"))}
PRUNE_GEN=""
record() {{ printf '%s\\n' "$1" >> "${{EVENTS}}"; }}
validate_quarantine() {{ record validate; }}
prepare_pruned_generation() {{ record prepare; PRUNE_GEN=.gen-prune-test; }}
activate_generation() {{ record activate; }}
ssh() {{ cat >/dev/null; record delete; printf '1\\n'; }}
""" + start.lstrip("\n") + block + "\n"
        result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
        recorded = events.read_text().splitlines() if events.exists() else []
        check("隔离发布区块执行成功", result.returncode == 0, result.stderr)
        check("先准备代际，再移除产物，最后切换",
              recorded == ["validate", "prepare", "delete", "activate"],
              repr(recorded))

print()
print("  索引改写：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
