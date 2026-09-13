#!/usr/bin/env python3
"""The resolver's hold on an older version is recorded with its reason, and
only that: a version the resolver could have installed is not excused."""

import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "build" / "resolved-versions.py"
spec = importlib.util.spec_from_file_location("resolved_versions", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

MASKED = """
!!! All ebuilds that could satisfy ">=app-i18n/fcitx-5.1.22:5" have been masked.
!!! One of the following masked packages is required to complete your request:
- app-i18n/fcitx-5.1.22::gentoo (masked by: ~amd64 keyword)

(dependency required by "app-i18n/fcitx-skk-5.1.11::gentoo-zh" [ebuild])
"""

VISIBLE = {
    "app-i18n/fcitx-skk": "5.1.11",
    "app-misc/current": "2.0",
    "app-misc/upgradable": "3.0",
    "app-misc/never-built": "1.0",
}
INSTALLED = {
    "app-i18n/fcitx-skk": "5.1.7-r2",
    "app-misc/current": "2.0",
    "app-misc/upgradable": "2.9",
}
PRETEND = {
    "app-i18n/fcitx-skk-5.1.11": (1, MASKED),
    "app-misc/upgradable-3.0": (0, "[ebuild  U ] app-misc/upgradable-3.0\n"),
}

asked = []


def pretend(cpv):
    asked.append(cpv)
    return PRETEND[cpv]


module.visible_of = lambda cp: VISIBLE.get(cp, "")
module.installed_of = lambda cp: INSTALLED.get(cp, "")
module.pretend = pretend

bad = 0


def check(name, ok, detail=""):
    global bad
    print(f"  {'✓' if ok else '✗'} {name}{('  ' + detail) if detail and not ok else ''}")
    if not ok:
        bad += 1


with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    (d / "packages.txt").write_text(
        "# comment\napp-i18n/fcitx-skk\napp-misc/current\n"
        "app-misc/upgradable\napp-misc/never-built\n\n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        module.main(str(d / "packages.txt"), str(d / "resolved.txt"))
    rows = [line.split("\t") for line in
            (d / "resolved.txt").read_text().splitlines()]

check("只对已装版本落后于可见版本的软件包问解析器",
      sorted(asked) == ["app-i18n/fcitx-skk-5.1.11", "app-misc/upgradable-3.0"],
      str(asked))
check("解析器拒绝的软件包连原因一起写出",
      rows == [["app-i18n/fcitx-skk", "5.1.7-r2", "5.1.11",
                '!!! All ebuilds that could satisfy ">=app-i18n/fcitx-5.1.22:5" '
                "have been masked.；- app-i18n/fcitx-5.1.22::gentoo "
                "(masked by: ~amd64 keyword)"]],
      str(rows))
check("解析器能装却没装的不写出，只在日志里点名",
      "!! app-misc/upgradable-3.0 可解析却未安装，已装 2.9" in out.getvalue(),
      out.getvalue())
check("保留的软件包在日志里带原因",
      ">>> 本频道解析不到 app-i18n/fcitx-skk-5.1.11，保留 5.1.7-r2：" in out.getvalue(),
      out.getvalue())

check("没有 masked 行时退回最后几行 !!!",
      module.reason_of("!!! a\n!!! b\n!!! c\n!!! d\n") == "!!! b；!!! c；!!! d")
check("解析器什么都没说时也有可读的原因",
      module.reason_of("") == "解析器未给出原因")

with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    (d / "packages.txt").write_text("app-misc/current\n")
    with contextlib.redirect_stdout(io.StringIO()):
        module.main(str(d / "packages.txt"), str(d / "resolved.txt"))
    check("没有保留时仍写出空文件，版本核对据此知道脚本已执行",
          (d / "resolved.txt").exists() and (d / "resolved.txt").read_text() == "")

sys.exit(1 if bad else 0)
