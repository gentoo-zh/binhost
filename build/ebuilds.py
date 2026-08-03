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

COMPILE_PHASE = re.compile(r"^(src_configure|src_compile)\s*\(\)", re.M)


def builds_from_source(text):
    ecl = inherits(text)
    if ecl & PREBUILT_ECLASS:
        return False
    return bool(ecl & BUILD_ECLASS) or bool(COMPILE_PHASE.search(text))


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


RESTRICT_ASSIGN = re.compile(
    r'(?P<pre>^[^\n#]*?)RESTRICT(?P<plus>\+?)='
    r'(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s#;)]+))', re.M)

BLOCK_OPEN = re.compile(r"^\s*(if|for|while|until|case)\b|\{\s*$|\(\)\s*\{")
BLOCK_CLOSE = ("fi", "done", "esac", "}", ";;")


def _assignments(text):
    for m in RESTRICT_ASSIGN.finditer(text):
        val = next((m.group(k) for k in ("dq", "sq", "bare")
                    if m.group(k) is not None), "")
        yield m, val


def restrict_tokens(text):
    cur = []
    for m, val in _assignments(text):
        cur = cur + val.split() if m.group("plus") else val.split()
    return set(cur)


EXPANSION = re.compile(r"[$`]")


def restrict_uncertain(text):
    for m, val in _assignments(text):
        if EXPANSION.search(val):
            return True
        if m.group("pre").strip():
            return True
        depth = 0
        for line in text[:m.start()].splitlines():
            s = line.strip()
            if BLOCK_OPEN.search(line):
                depth += 1
            elif s in BLOCK_CLOSE:
                depth = max(0, depth - 1)
        if depth:
            return True
    return False


def restricts_bindist(text):
    return any("bindist" in val for _, val in _assignments(text))


def inherits(text):
    return set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())


def read_list(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
