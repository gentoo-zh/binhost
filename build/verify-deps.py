#!/usr/bin/env python3
"""
verify-deps.py <Packages> [--installed <cpv list>]

Checks an index against itself: every runtime dependency of every stanza must
match a published CPV, or name a package the base system already provides.

The base system is read from --installed, the package list the build container
wrote from its own vdb. Without that file there is no way to tell a dependency
the consumer already has from one this round failed to build, so every atom the
index cannot satisfy counts as a finding.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ebuilds import index_db, runtime_atoms, split_cpv   # noqa: E402

RUNTIME_FIELDS = ("RDEPEND", "PDEPEND", "IDEPEND")

EXCEPTIONS = pathlib.Path(__file__).with_name("dep-exceptions.txt")


def read_exceptions(path=None):
    """atom -> reason. Atoms listed here are known not to be satisfiable here."""
    p = pathlib.Path(path or EXCEPTIONS)
    out = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        atom, _, reason = line.partition("\t")
        out[atom.strip()] = reason.strip()
    return out


def parse(text):
    out = []
    for s in text.split("\n\n")[1:]:
        if not s.strip():
            continue
        f = dict(re.findall(r"^(\w+): (.*)$", s, re.M))
        if f.get("CPV"):
            out.append(f)
    return out


def read_installed(path):
    """CPs the build root already provides, or None when not supplied."""
    if not path:
        return None
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    out = set()
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(split_cpv(line)[0] or line)
    return out


def check(fields, installed=None):
    """(unsatisfied, absent, seen).

    unsatisfied: atoms nothing published satisfies and the base system does
    not provide either. Both a wrong version of a carried package and a
    package nobody has count here.
    base: atoms the base system provides, which the consumer already has.
    seen: every atom the index names, so a stale exception can be told from
    one that simply does not apply to this index.

    The base system is matched by package name only: installed.txt carries no
    slot or USE metadata, so checking the whole atom against it would reject
    packages the root plainly has.

    With no installed list every unmatched atom is a finding: guessing that an
    absent package must be part of the base system is what hid failed builds.
    """
    db = index_db(fields)
    unsatisfied, base, seen = {}, {}, set()

    def satisfied(node, cpv, out):
        """True when the index or the base system satisfies this node.

        The base system counts here rather than after the walk: a || group
        whose only usable branch is a base system package is satisfied, and
        judging its branches on the index alone reports the whole group as
        missing.
        """
        if isinstance(node, list):
            if node and node[0] == "||":
                # Each branch gets its own diagnostics. A branch that failed is
                # only a finding when no branch at all could be satisfied.
                tries = []
                for branch in node[1:]:
                    mine = []
                    if satisfied(branch, cpv, mine):
                        return True
                    tries.append(mine)
                for mine in tries:
                    out.extend(mine)
                return False
            return all([satisfied(c, cpv, out) for c in node])
        if node.blocker:
            return True
        seen.add(str(node))
        if db.match(node):
            return True
        if installed is not None and node.cp in installed:
            base.setdefault(str(node), set()).add(cpv)
            return True
        out.append(node)
        return False

    for f in fields:
        cpv = f["CPV"]
        nodes = runtime_atoms(" ".join(f.get(k, "") for k in RUNTIME_FIELDS))
        if nodes is None:
            unsatisfied.setdefault(f"<{cpv} 的依赖无法解析>", set()).add(cpv)
            continue
        for node in nodes:
            missing = []
            satisfied(node, cpv, missing)
            for atom in missing:
                unsatisfied.setdefault(str(atom), set()).add(cpv)
    return unsatisfied, base, seen


def main(path, exceptions=None, installed=None):
    fields = parse(pathlib.Path(path).read_text())
    if not fields:
        sys.exit(f"{path} 中没有任何 stanza")
    try:
        have = read_installed(installed)
    except FileNotFoundError as e:
        sys.exit(f"读不到基础系统清单 {e}，无法判定缺失的依赖，本轮不通过")
    unsatisfied, base, seen = check(fields, have)
    known = read_exceptions(exceptions)

    accepted = {a for a in unsatisfied if a in known}
    stale = sorted((set(known) & seen) - set(unsatisfied))
    unsatisfied = {a: w for a, w in unsatisfied.items() if a not in known}

    if have is None:
        print("!! 未提供基础系统清单，索引之外的依赖一律计为未满足", file=sys.stderr)
    print(f"索引 {len(fields)} 个，{len(base)} 个原子由基础系统提供，"
          f"{len(accepted)} 个是已列出的例外")
    for atom in stale:
        print(f"!! 例外 {atom} 本轮已能满足，应从 dep-exceptions.txt 删除",
              file=sys.stderr)
    if unsatisfied:
        print(f"!! {len(unsatisfied)} 个运行期依赖没有一个已发布版本满足，"
              f"基础系统也不提供", file=sys.stderr)
        for atom, who in sorted(unsatisfied.items())[:20]:
            print(f"   {atom}  <- {' '.join(sorted(who)[:3])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    inst = None
    if "--installed" in args:
        i = args.index("--installed")
        inst = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    sys.exit(main(args[0] if args else "/srv/pub/binpkgs/x86-64/Packages",
                  installed=inst))
