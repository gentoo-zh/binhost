#!/usr/bin/env python3
"""
resolved-versions.py <packages.txt> <output>

Runs inside the build container after the list has been built. For every
listed package whose newest visible version is not the one installed, asks the
resolver why. When the newest version cannot be pulled in under this channel's
keywords (a dependency that is still ~arch in ::gentoo, most often), the
package is written out with the resolver's reason so that check-versions.py
can tell a deliberate hold from a build that silently fell behind.

Output lines are tab separated: category/package, installed version, newest
visible version, reason.
"""
import pathlib
import re
import subprocess
import sys

ATOM_RE = r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$"

EMERGE = ["emerge", "--pretend", "--quiet", "--usepkg", "--with-bdeps=y"]


def read_list(path):
    return [line.strip() for line in pathlib.Path(path).read_text().splitlines()
            if re.match(ATOM_RE, line.strip())]


def version_of(cpv, cp):
    return cpv[len(cp) + 1:]


def visible_of(cp):
    """Newest version the channel may install, ignoring dependencies."""
    import portage
    cpv = portage.db[portage.root]["porttree"].dbapi.xmatch(
        "bestmatch-visible", cp)
    return version_of(cpv, cp) if cpv else ""


def installed_of(cp):
    import portage
    from portage.versions import best
    cpv = best(portage.db[portage.root]["vartree"].dbapi.match(cp))
    return version_of(cpv, cp) if cpv else ""


def newer(a, b):
    from portage.versions import vercmp
    return (vercmp(a, b) or 0) > 0


def pretend(cpv):
    """(exit code, output) of resolving exactly this version."""
    p = subprocess.run(EMERGE + [f"={cpv}"], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def reason_of(output):
    lines = [l.strip() for l in output.splitlines()]
    masked = [l for l in lines if "masked by:" in l or "have been masked" in l]
    if masked:
        return "；".join(masked)
    tail = [l for l in lines if l.startswith("!!!")]
    return "；".join(tail[-3:]) if tail else "解析器未给出原因"


def resolve(cps):
    """[(cp, installed, visible, reason)] for the packages held back by the
    resolver; packages the resolver could have upgraded are reported on stdout
    and left out, so the version check still treats them as behind.

    A package with nothing installed is asked about too: when the resolver
    refuses its newest version the channel has nothing to publish for it, and
    that is a refusal to record, not a build that went missing. installed is
    empty in that row.
    """
    held = []
    for cp in cps:
        visible, installed = visible_of(cp), installed_of(cp)
        if not visible or (installed and not newer(visible, installed)):
            continue
        rc, output = pretend(f"{cp}-{visible}")
        if rc == 0:
            have = f"，已装 {installed}" if installed else ""
            print(f"!! {cp}-{visible} 可解析却未安装{have}")
            continue
        held.append((cp, installed, visible, reason_of(output)))
    return held


def main(listfile, output):
    held = resolve(read_list(listfile))
    for cp, installed, visible, reason in held:
        kept = f"保留 {installed}" if installed else "没有旧版本可保留"
        print(f">>> 本频道解析不到 {cp}-{visible}，{kept}：{reason}")
    pathlib.Path(output).write_text(
        "".join(f"{cp}\t{installed}\t{visible}\t{reason}\n"
                for cp, installed, visible, reason in held))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
