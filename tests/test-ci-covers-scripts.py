#!/usr/bin/env python3
"""Every script directory has to appear in the CI globs that lint it, and
every test file has to be named by a CI step that runs it.

py_compile and shellcheck take explicit globs, so moving scripts into a new
directory drops them out of CI silently: nothing references the old path any
more, so a grep for stale references comes back clean while the new directory
is checked by nothing at all. That happened twice while splitting build/.

tests/ is deliberately outside the py_compile glob: those files are executed
by CI one by one, which subsumes compiling them. That per-file listing is the
second gap: a new test passes locally, nobody adds the step, and it never runs
again. tests/test-publish-lock.sh and tests/test-site-sync-check.sh were
written, merged and never executed by CI.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"

PY_EXEMPT = {"tests"}
SH_EXEMPT = set()

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def globs_of(command):
    """Directories named by `dir/*.ext` operands of the given CI command."""
    text = WORKFLOW.read_text()
    m = re.search(rf"^\s*run: .*\b{re.escape(command)}\b([^\n]*)$", text, re.M)
    if not m:
        return None
    return set(re.findall(r"([A-Za-z0-9._/-]+)/\*\.\w+", m.group(1)))


def dirs_holding(suffix):
    """Repo directories that hold at least one file with this suffix."""
    out = set()
    for f in ROOT.rglob(f"*{suffix}"):
        if any(p in {".git", "__pycache__", "node_modules"} for p in f.parts):
            continue
        rel = f.relative_to(ROOT)
        if len(rel.parts) == 1:
            continue
        out.add(str(rel.parent))
    return out


py = globs_of("py_compile")
sh = globs_of("shellcheck")
check("读到了 py_compile 的目录清单", py is not None, str(py))
check("读到了 shellcheck 的目录清单", sh is not None, str(sh))
if py is None or sh is None:
    sys.exit(1)

for d in sorted(dirs_holding(".py") - PY_EXEMPT):
    check(f"{d}/ 的 .py 在 py_compile 里", d in py,
          "已列出：" + " ".join(sorted(py)))

for d in sorted(dirs_holding(".sh") - SH_EXEMPT):
    check(f"{d}/ 的 .sh 在 shellcheck 里", d in sh,
          "已列出：" + " ".join(sorted(sh)))

workflow = WORKFLOW.read_text()
run_by_ci = set(re.findall(r"tests/(test-[A-Za-z0-9._-]+)", workflow))
for f in sorted(p.name for p in (ROOT / "tests").glob("test-*")):
    check(f"CI 有执行 tests/{f} 的步骤", f in run_by_ci)

print()
print("  CI 脚本覆盖：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
