#!/usr/bin/env python3
"""quarantine.txt must carry exactly the products that cannot wait.

publish.sh removes everything listed there from the public path before the new
generation is swapped in. Anything that cannot be redistributed has to be on
that list; a package that merely left the build list must not be, or a failed
round would take a working product offline.

test-stage-index.py checks which state select() assigns. This checks what
main() then writes, which is the part publish.sh acts on.
"""

import importlib.util
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "stage_index", ROOT / "build" / "stage-index.py")
stage_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_index)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 999\nTIMESTAMP: 1\nVERSION: 0"

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def quarantine(restrict=None, license_state="yes", restrict_now="",
               excluded=(), masked=(), in_overlay=True):
    """Stage one package and return the lines publish.sh would act on."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkg"
        (pkg / "app-misc").mkdir(parents=True)
        (pkg / "app-misc" / "a-1.gpkg.tar").write_text("inside\n")
        stage = d / "stage"
        stage.mkdir()
        lines = ["CPV: app-misc/a-1", "PATH: app-misc/a-1.gpkg.tar",
                 "REPO: gentoo-zh", "EAPI: 8", "SLOT: 0"]
        if restrict:
            lines.append(f"RESTRICT: {restrict}")
        (pkg / "Packages").write_text(HEADER + "\n\n" + "\n".join(lines) + "\n")

        overlay = d / "overlay"
        prof = overlay / "profiles"
        prof.mkdir(parents=True)
        (prof / "repo_name").write_text("gentoo-zh\n")
        (prof / "package.mask").write_text(
            "".join(f"# masked\n{cp}\n" for cp in masked))
        if in_overlay:
            ebuild = overlay / "app-misc" / "a"
            ebuild.mkdir(parents=True)
            (ebuild / "a-1.ebuild").write_text("EAPI=8\n")

        exclude_file = d / "excluded.txt"
        exclude_file.write_text("".join(f"{cp}\treason\n" for cp in excluded))

        old_tree = stage_index.GENTOO_TREE
        old_policy = stage_index.portage_policy
        stage_index.GENTOO_TREE = "/nonexistent/gentoo"
        # main() resolves policy through portage_policy; swapping it keeps the
        # real code path while supplying verdicts a fixture cannot produce.
        stage_index.portage_policy = lambda _overlay: (
            lambda cpv, repo: restrict_now,
            lambda cpv, fields: license_state,
            lambda cpv, repo: "")
        try:
            stage_index.main(
                str(pkg), str(stage), overlay=str(overlay),
                rev="a" * 40, gentoo_rev="b" * 40,
                excluded_files=(str(exclude_file),))
        except SystemExit:
            pass
        finally:
            stage_index.GENTOO_TREE = old_tree
            stage_index.portage_policy = old_policy
        f = stage / "quarantine.txt"
        return f.read_text().split() if f.exists() else []


PATH = "app-misc/a-1.gpkg.tar"

print(">>> 不能等的：立即从公开路径移除")
check("ebuild 现在是 RESTRICT=bindist",
      quarantine(restrict_now="bindist") == [PATH])
check("缓存 stanza 记录了 bindist",
      quarantine(restrict="bindist") == [PATH])
check("许可证不可再分发", quarantine(license_state="no") == [PATH])
check("再分发资格无法确认", quarantine(license_state="unknown") == [PATH])

print(">>> 可以等的：留到新索引切换成功后再清理")
check("只是被 mask", quarantine(masked=("app-misc/a",)) == [])
check("只是移出收录清单", quarantine(excluded=("app-misc/a",)) == [])
check("ebuild 已从 overlay 删除", quarantine(in_overlay=False) == [])
check("完全正常的产物不进清单", quarantine() == [])

print()
print("  隔离清单：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
