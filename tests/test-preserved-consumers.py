#!/usr/bin/env python3
"""The checker classifies a consumer the way portage's own set does."""

import pathlib
import subprocess
import sys
import tempfile
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHECKER = ROOT / "build" / "preserved-consumers.py"

# A stand-in for portage: enough of the vardb, registry and linkmap surface for
# the checker to run, with the answers each case needs.
STUB = '''
import sys, types

class InvalidData(Exception):
    pass

exception = types.ModuleType("portage.exception")
exception.InvalidData = InvalidData

class Registry:
    def __init__(self, preserved):
        self._preserved = preserved
    def load(self):
        pass
    def getPreservedLibs(self):
        return self._preserved

class LinkMap:
    def __init__(self, consumers, owners):
        self._consumers = consumers
        self._owners = owners
    def rebuild(self):
        pass
    def _obj_key(self, path):
        return path
    def findConsumers(self, path, greedy=True):
        return self._consumers.get(path, [])
    def getOwners(self, path):
        return self._owners.get(path, [])

class PkgStr(str):
    def __new__(cls, cp, slot):
        self = super().__new__(cls, cp)
        self.cp = cp
        self.slot = slot
        return self

class VarDB:
    def __init__(self, preserved, consumers, owners, installed):
        self._plib_registry = Registry(preserved)
        self._linkmap = LinkMap(consumers, owners)
        self._installed = installed
    def _pkg_str(self, cpv, repo):
        if cpv not in self._installed:
            raise KeyError(cpv)
        return PkgStr(*self._installed[cpv])

portage = types.ModuleType("portage")
portage.exception = exception
portage.root = "/"
portage.db = {"/": {"vartree": types.SimpleNamespace(dbapi=VarDB(
    PRESERVED, CONSUMERS, OWNERS, INSTALLED))}}
sys.modules["portage"] = portage
sys.modules["portage.exception"] = exception
'''

LIB = "/usr/lib64/libbfd-2.46.0.so"
CPV = "sys-libs/binutils-libs-2.46.1"


def run(preserved, consumers, owners, installed):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(f"PRESERVED = {preserved!r}\n")
        f.write(f"CONSUMERS = {consumers!r}\n")
        f.write(f"OWNERS = {owners!r}\n")
        f.write(f"INSTALLED = {installed!r}\n")
        f.write(STUB)
        f.write(textwrap.dedent(f'''
            exec(compile(open({str(CHECKER)!r}).read(), {str(CHECKER)!r}, "exec"))
        '''))
        probe = f.name
    r = subprocess.run([sys.executable, probe], capture_output=True, text=True)
    pathlib.Path(probe).unlink()
    return r.returncode, r.stdout


cases = []


def case(name, rc, expect, *args):
    got_rc, out = run(*args)
    ok = got_rc == rc and all(e in out for e in expect)
    cases.append((ok, name, got_rc, rc, out))


# Nothing preserved at all.
case("登记表为空就放行", 0, [], {}, {}, {}, {})

# An entry nothing links to: portage leaves it until a later merge notices.
case("有登记但没有使用者", 0, ["仍在登记但没有使用者"],
     {CPV: [LIB]}, {LIB: []}, {}, {})

# The binutils-libs shape: its own preserved libs reference each other, and
# they do belong to the installed package, so only the internal-consumer rule
# keeps this from being reported as an uncovered rebuild.
case("同套件的保留库不算使用者", 0, ["仍在登记但没有使用者"],
     {CPV: [LIB, "/usr/lib64/libctf.so"]},
     {LIB: ["/usr/lib64/libctf.so"], "/usr/lib64/libctf.so": []},
     {"/usr/lib64/libctf.so": [CPV]},
     {CPV: ("sys-libs/binutils-libs", "0")})

# A consumer no installed package owns. @preserved-rebuild cannot act on it,
# so failing the build asks for something portage has no way to deliver.
case("无主使用者放行并报告", 0, ["无主使用者"],
     {CPV: [LIB]}, {LIB: ["/usr/bin/orphan"]}, {"/usr/bin/orphan": []}, {})

# A consumer that maps to an installed package: the rebuild was asked to cover
# it and did not.
case("有主使用者拦下", 1, ["重建没有覆盖", "app-emulation/looking-glass:0"],
     {CPV: [LIB]},
     {LIB: ["/usr/bin/looking-glass-client"]},
     {"/usr/bin/looking-glass-client": ["app-emulation/looking-glass-0_beta7"]},
     {"app-emulation/looking-glass-0_beta7": ("app-emulation/looking-glass", "0")})

# An owner recorded in the linkmap but gone from the vdb resolves to nothing,
# which portage treats as expected rather than as a failure.
case("登记的拥有者已不在 vdb 视为无主", 0, ["无主使用者"],
     {CPV: [LIB]},
     {LIB: ["/usr/bin/gone"]},
     {"/usr/bin/gone": ["app-misc/gone-1"]},
     {})

# Owned and unowned consumers on the same library: the owned one decides.
case("有主与无主并存时拦下", 1, ["重建没有覆盖", "无主使用者"],
     {CPV: [LIB]},
     {LIB: ["/usr/bin/orphan", "/usr/bin/owned"]},
     {"/usr/bin/orphan": [], "/usr/bin/owned": ["app-misc/owned-1"]},
     {"app-misc/owned-1": ("app-misc/owned", "0")})

fail = 0
for ok, name, got, want, out in cases:
    if ok:
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}\n      rc={got}，应为 {want}\n      输出：{out.strip()}")

print()
if fail:
    print(f">>> {len(cases) - fail} 过，{fail} 不过")
    sys.exit(1)
print(f">>> {len(cases)} 项全过")
