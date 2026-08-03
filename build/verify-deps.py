#!/usr/bin/env python3
"""
verify-deps.py <Packages>

Checks the published index against itself: every runtime dependency of every
stanza must either match a published CPV, or name a package the index does not
carry at all, which is the stage3 base the consumer already has.

A dependency whose package is in the index but whose version, slot, repository
or USE constraint no match satisfies is a real defect: staging published a
version nothing can use. That is what makes this exit non-zero.
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


def cp_of(atom):
    bare = re.sub(r"^[<>=~!]*", "", str(atom)).split("[")[0]
    bare = bare.split("::")[0].split(":")[0]
    return split_cpv(bare)[0]


def check(fields):
    """(unsatisfied, absent, seen).

    unsatisfied: atoms whose package is published but no version satisfies.
    absent: atoms for packages the index does not carry at all.
    seen: every atom the index names, so a stale exception can be told from
    one that simply does not apply to this index.
    """
    db = index_db(fields)
    carried = {split_cpv(f["CPV"])[0] for f in fields}
    unsatisfied, absent, seen = {}, {}, set()

    def walk(node, cpv):
        if isinstance(node, list):
            if node and node[0] == "||":
                return any(walk(b, cpv) for b in node[1:])
            return all(walk(c, cpv) for c in node)
        if node.blocker:
            return True
        seen.add(str(node))
        if db.match(node):
            return True
        bucket = unsatisfied if cp_of(node) in carried else absent
        bucket.setdefault(str(node), set()).add(cpv)
        return False

    for f in fields:
        cpv = f["CPV"]
        nodes = runtime_atoms(" ".join(f.get(k, "") for k in RUNTIME_FIELDS))
        if nodes is None:
            unsatisfied.setdefault(f"<{cpv} 的依赖无法解析>", set()).add(cpv)
            continue
        for node in nodes:
            walk(node, cpv)
    return unsatisfied, absent, seen


def main(path, exceptions=None):
    fields = parse(pathlib.Path(path).read_text())
    if not fields:
        sys.exit(f"{path} 中没有任何 stanza")
    unsatisfied, absent, seen = check(fields)
    known = read_exceptions(exceptions)

    accepted = {a for a in unsatisfied if a in known}
    stale = sorted((set(known) & seen) - set(unsatisfied))
    unsatisfied = {a: w for a, w in unsatisfied.items() if a not in known}

    print(f"索引 {len(fields)} 个，运行期依赖里 {len(absent)} 个原子指向索引不收录的包，"
          f"由基础系统提供；{len(accepted)} 个是已列出的例外")
    for atom in stale:
        print(f"!! 例外 {atom} 本轮已能满足，应从 dep-exceptions.txt 删除",
              file=sys.stderr)
    if unsatisfied:
        print(f"!! {len(unsatisfied)} 个原子的包已发布，但没有一个已发布版本满足它",
              file=sys.stderr)
        for atom, who in sorted(unsatisfied.items())[:20]:
            print(f"   {atom}  <- {' '.join(sorted(who)[:3])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "/srv/pub/binpkgs/x86-64/Packages"))
