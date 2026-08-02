#!/usr/bin/env python3

import pathlib
import re
import sys

try:
    from portage.versions import vercmp
except ImportError:
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")

ATOM = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$")

BUILD_ECLASS = {
    "cmake", "meson", "go-module", "cargo", "autotools", "gnome2",
    "distutils-r1", "dotnet-pkg", "qmake-utils", "waf-utils", "scons-utils",
}
PREBUILT_ECLASS = {"unpacker", "rpm", "java-pkg-simple"}


def read_mask(overlay):
    p = pathlib.Path(overlay) / "profiles" / "package.mask"
    if not p.exists():
        return set()
    out = set()
    for raw in p.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"[a-z0-9-]+/[A-Za-z0-9._+-]+", line.lstrip("<>=~!"))
        if m:
            out.add(re.sub(r"-[0-9][^/]*$", "", m.group(0)))
    return out


def version_of(ebuild, pn):
    return ebuild.name[len(pn) + 1:-len(".ebuild")]


def newest_ebuild(pkgdir):
    pkgdir = pathlib.Path(pkgdir)
    ebuilds = [e for e in pkgdir.glob("*.ebuild") if "9999" not in e.name]
    if not ebuilds:
        return None
    pn = pkgdir.name
    best = ebuilds[0]
    for e in ebuilds[1:]:
        if (vercmp(version_of(e, pn), version_of(best, pn)) or 0) > 0:
            best = e
    return best


def accepts_amd64(keywords):
    ks = set(keywords.split())
    if "-amd64" in ks:
        return False
    if ks & {"amd64", "~amd64"}:
        return True
    return bool(ks & {"*", "~*"})


def keywords_of(text):
    kw = re.findall(r'^\s*KEYWORDS="([^"]*)"', text, re.M)
    return kw[-1] if kw else None


def restricts_bindist(text):
    return any("bindist" in r
               for r in re.findall(r'^\s*RESTRICT="([^"]*)"', text, re.M))


def inherits(text):
    return set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())


def read_list(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
