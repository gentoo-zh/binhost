#!/usr/bin/env python3
"""Report built packages whose := dependencies pin an outdated subslot.

A `cat/pkg:slot/sub=` dependency records the subslot that was current when the
package was built. Once the dependency changes subslot, the built package no
longer applies on a system whose tree has moved on, and portage says nothing:
it silently builds from source instead.
"""

import argparse
import pathlib
import re
import sys

# cat/pkg:slot/subslot=, optionally preceded by ! or !! and a version operator
SLOT_OP = re.compile(
    r"(?:^|\s)!{0,2}[<>=~]*"
    r"(?P<cp>[a-z0-9][a-z0-9+._-]*/[A-Za-z0-9+._-]+?)"
    r"(?:-[0-9][A-Za-z0-9._-]*)?"
    r":(?P<slot>[A-Za-z0-9+._-]*)/(?P<sub>[A-Za-z0-9+._-]+)="
)


def read_stanzas(path):
    """The first block is the header; every later block is one package."""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    chunks = text.split("\n\n")
    return chunks[0], [c for c in chunks[1:] if c.strip()]


def accepted_keywords(header):
    """The index records the keywords its generation was built with."""
    return field(header, "ACCEPT_KEYWORDS")


def field(stanza, name):
    m = re.search(rf"^{name}: (.*)$", stanza, re.M)
    return m.group(1) if m else ""


class Tree:
    """The subslot of the best version a user of this channel can see.

    Visibility comes from portage rather than a plain version sort, because
    package.mask and the profile decide what is installable; taking the highest
    version would read a masked one as current. The keywords come from the
    index being checked, not from the machine running the check: a stable
    channel must not be measured against a version only ~arch can install.
    """

    def __init__(self, keywords):
        import portage
        from portage.dbapi.porttree import portdbapi

        settings = portage.config(clone=portage.settings)
        if keywords:
            settings.unlock()
            settings["ACCEPT_KEYWORDS"] = keywords
            settings.backup_changes("ACCEPT_KEYWORDS")
            settings.lock()
        self.dbapi = portdbapi(mysettings=settings)
        self.cache = {}

    def current_subslot(self, cp):
        if cp not in self.cache:
            best = self.dbapi.xmatch("bestmatch-visible", cp)
            slot = self.dbapi.aux_get(best, ["SLOT"])[0] if best else ""
            self.cache[cp] = slot.split("/", 1)[1] if "/" in slot else None
        return self.cache[cp]


def stale_in(stanza, tree):
    """Outdated := dependencies of one package, each dependency named once."""
    seen = set()
    out = []
    # RDEPEND only: DEPEND and BDEPEND are build time, and a subslot change
    # there does not affect whether the built package applies.
    for m in SLOT_OP.finditer(field(stanza, "RDEPEND")):
        cp = m.group("cp")
        if cp in seen:
            continue
        seen.add(cp)
        current = tree.current_subslot(cp)
        if current is None:
            continue
        if current != m.group("sub"):
            out.append((cp, f"{m.group('slot')}/{m.group('sub')}", current))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="要检查的 Packages 索引")
    ap.add_argument("--alert", help="有发现时写到这里，供告警取用")
    args = ap.parse_args()

    header, stanzas = read_stanzas(args.index)
    tree = Tree(accepted_keywords(header))

    findings = []
    for stanza in stanzas:
        cpv = field(stanza, "CPV")
        if not cpv:
            continue
        for cp, recorded, current in stale_in(stanza, tree):
            findings.append((cpv, cp, recorded, current))

    print(f">>> 子槽检查：{len(stanzas)} 个包，{len(findings)} 处依赖子槽已过期")
    if not findings:
        if args.alert:
            pathlib.Path(args.alert).unlink(missing_ok=True)
        return 0

    lines = [
        f"{cpv} 依赖 {cp}，记录 {recorded}，树里现在是 {current}"
        for cpv, cp, recorded, current in sorted(findings)
    ]
    for line in lines:
        print(f"    {line}")
    if args.alert:
        pathlib.Path(args.alert).write_text(
            "这些包在树已经更新的系统上不适用，portage 会改为从源码构建：\n"
            + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
