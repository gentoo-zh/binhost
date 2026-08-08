#!/usr/bin/env python3
"""kernel-series reports the newest version of each major.minor series.

The archive keeps one build per series, so this list decides what gets built.
Taking it from the overlay means a bump inside a series needs no edit and a new
series appears on its own.

The grouping and the version comparison are tested against a stand-in
repository rather than a real one: building an overlay portage will read takes
a profile, a categories file and permissions that differ between this machine
and CI, and none of that is what these rules are about.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "kernel-series.py"
sys.path.insert(0, str(ROOT / "build"))

spec = importlib.util.spec_from_file_location("kernel_series", SCRIPT)
ks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ks)

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


class FakeDb:
    """Answers match() the way portdbapi does, with CPV strings."""

    def __init__(self, package, versions):
        self.cpvs = [f"{package}-{v}" for v in versions]

    def match(self, _package):
        return self.cpvs


PKG = "sys-kernel/demo-kernel"


def series(versions):
    return ks.newest_per_series(FakeDb(PKG, versions), PKG)


check("按主次分组", ks.series_of("6.18.43") == "6.18" and ks.series_of("7.1.7") == "7.1",
      f'{ks.series_of("6.18.43")} {ks.series_of("7.1.7")}')
check("只有一段版本号时原样返回", ks.series_of("7") == "7", ks.series_of("7"))

check("两条线各报一个版本", series(["6.18.43", "7.1.7"]) == {"6.18": "6.18.43", "7.1": "7.1.7"},
      str(series(["6.18.43", "7.1.7"])))
check("同一条线里只报最新的", series(["6.18.41", "6.18.43", "7.1.7"])["6.18"] == "6.18.43",
      str(series(["6.18.41", "6.18.43", "7.1.7"])))
check("版本比较不是字串比较", series(["6.18.9", "6.18.10"])["6.18"] == "6.18.10",
      "字串比较会选 6.18.9：" + str(series(["6.18.9", "6.18.10"])))
check("修订号也算进比较", series(["6.18.43", "6.18.43-r1"])["6.18"] == "6.18.43-r1",
      str(series(["6.18.43", "6.18.43-r1"])))
check("一个版本都没有时不报任何线", series([]) == {}, str(series([])))

print()
print("  内核线：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
