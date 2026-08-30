#!/usr/bin/env python3
"""
verify-deps.py <Packages> [--installed <base snapshot>]
               [--available <binrepo snapshot>] [--source <tree snapshot>]

Checks an index against itself: every runtime dependency of every stanza must
match a published CPV, name a package the base system already provides, or
match a package captured from the configured Gentoo binary repository or the
Gentoo and gentoo-zh source trees.

The base system is read from the immutable vdb snapshot written before emerge.
Without that file there is no way to tell a dependency the consumer already has
from one this round failed to build, so every atom the index cannot satisfy
counts as a finding.
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ebuilds import (                                     # noqa: E402
    default_use, index_db, isolated_portage_config, runtime_atoms, source_only,
    repository_revision, split_cpv,
)
from portage.dep import Atom                             # noqa: E402

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
        atom, tab, reason = line.partition("\t")
        # An exception without a reason is almost always a mistyped line, and
        # accepting it silently drops a real unsatisfied dependency.
        if not tab or not reason.strip():
            raise ValueError(f"{p}: 例外缺少制表符与理由：{line}")
        out[atom.strip()] = reason.strip()
    return out


def parse(text):
    out = []
    for s in text.split("\n\n")[1:]:
        if not s.strip():
            continue
        f = dict(re.findall(r"^(\w+): ?(.*)$", s, re.M))
        if f.get("CPV"):
            out.append(f)
    return out


SNAPSHOT_FIELDS = ("CPV", "SLOT", "USE", "IUSE", "EAPI", "REPO")


def read_snapshot(path, description):
    """Return fields and a Portage database for a structured snapshot."""
    if not path:
        return [], None
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    text = p.read_text()
    fields = parse(text)
    declared = re.search(r"^PACKAGES: ([0-9]+)$", text, re.M)
    if (not declared or int(declared.group(1)) != len(fields)
            or any(not set(SNAPSHOT_FIELDS).issubset(field) for field in fields)):
        raise ValueError(f"{path} 不是完整的{description}")
    return fields, index_db(fields)


def read_source_index(path):
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    text = p.read_text()
    fields = parse(text)
    declared = re.search(r"^PACKAGES: ([0-9]+)$", text, re.M)
    if not declared or int(declared.group(1)) != len(fields) or not fields:
        raise ValueError(f"{path} 不是完整的 binrepo 索引")
    return text, fields


def write_snapshot(path, header, fields):
    stanzas = []
    for field in fields:
        values = {name: field.get(name, "") for name in SNAPSHOT_FIELDS}
        values["SLOT"] = values["SLOT"] or "0"
        values["EAPI"] = values["EAPI"] or "0"
        values["BUILD_ID"] = field.get("BUILD_ID", "0") or "0"
        values["BUILD_TIME"] = field.get("BUILD_TIME", "0") or "0"
        stanzas.append("\n".join(
            f"{name}: {values[name]}".rstrip() for name in
            (*SNAPSHOT_FIELDS, "BUILD_ID", "BUILD_TIME")))
    text = "\n".join(header)
    if stanzas:
        text += "\n\n" + "\n\n".join(stanzas)
    pathlib.Path(path).write_text(text + "\n")


def write_available(path, source_text, source_fields, atoms):
    cps = {Atom(atom).cp for atom in atoms}
    selected = [field for field in source_fields
                if split_cpv(field["CPV"])[0] in cps]
    source_count = re.search(r"^PACKAGES: ([0-9]+)$", source_text, re.M).group(1)
    source_timestamp = re.search(r"^TIMESTAMP: ([0-9]+)$", source_text, re.M)
    header = [f"PACKAGES: {len(selected)}", f"SOURCE_PACKAGES: {source_count}"]
    if source_timestamp:
        header.append(f"SOURCE_TIMESTAMP: {source_timestamp.group(1)}")
    header.append("VERSION: 1")
    write_snapshot(path, header, selected)


def source_resolver(tree, overlay=None, accept_keywords="~amd64",
                    overlay_keywords=None):
    import os
    import portage

    env = dict(os.environ)
    env["ACCEPT_KEYWORDS"] = accept_keywords
    # Source availability is independent of the user's accepted licenses.
    env["ACCEPT_LICENSE"] = "*"
    repositories = (
        "[DEFAULT]\nmain-repo = gentoo\n\n"
        f"[gentoo]\nlocation = {pathlib.Path(tree).resolve()}\n")
    if overlay is not None:
        repositories += (
            "\n[gentoo-zh]\n"
            f"location = {pathlib.Path(overlay).resolve()}\n"
            "masters = gentoo\n")
    env["PORTAGE_REPOSITORIES"] = repositories
    package_keywords = ()
    if overlay is not None and overlay_keywords:
        package_keywords = (f"*/*::gentoo-zh {overlay_keywords}",)
    database = portage.portdbapi(mysettings=isolated_portage_config(
        env, package_accept_keywords=package_keywords))

    def resolve(atom):
        fields = []
        names = ("SLOT", "IUSE", "EAPI", "repository")
        for cpv in database.xmatch("match-visible", atom):
            values = dict(zip(names, database.aux_get(cpv, names)))
            fields.append({
                "CPV": cpv,
                "SLOT": values["SLOT"],
                "USE": default_use(values["IUSE"]),
                "IUSE": values["IUSE"],
                "EAPI": values["EAPI"],
                "REPO": values["repository"],
            })
        return fields

    return resolve


def select_source(atoms, resolve):
    selected = {}
    for value in atoms:
        atom = Atom(value)
        if atom.use is not None and not source_only(atom.cp):
            continue
        for field in resolve(atom):
            key = (field["CPV"], field.get("REPO", ""))
            selected[key] = field
    return [selected[key] for key in sorted(selected)]


def write_source(path, tree, atoms, overlay=None, resolve=None,
                 accept_keywords="~amd64", overlay_keywords=None):
    fields = select_source(
        atoms, resolve or source_resolver(
            tree, overlay, accept_keywords, overlay_keywords))
    header = [f"PACKAGES: {len(fields)}", "SOURCE_REPOSITORY: gentoo"]
    revision = repository_revision(tree)
    if revision:
        header.append(f"SOURCE_REVISION: {revision}")
    if overlay is not None:
        header.append("SOURCE_OVERLAY_REPOSITORY: gentoo-zh")
        overlay_revision = repository_revision(overlay)
        if overlay_revision:
            header.append(f"SOURCE_OVERLAY_REVISION: {overlay_revision}")
    header.append("VERSION: 1")
    write_snapshot(path, header, fields)


def check(fields, installed=None, available=None, source=None):
    """(unsatisfied, base, external, source, seen).

    unsatisfied: atoms nothing published satisfies and the base system does
    not provide either. Both a wrong version of a carried package and a
    package nobody has count here.
    base: atoms the base system provides, which the consumer already has.
    external: atoms the captured Gentoo binrepo provides.
    source: atoms the captured Gentoo source tree provides.
    seen: every atom the index names, so a stale exception can be told from
    one that simply does not apply to this index.

    With no installed list every unmatched atom is a finding: guessing that an
    absent package must be part of the base system is what hid failed builds.
    """
    db = index_db(fields)
    unsatisfied, base, external, source_matches, seen = {}, {}, {}, {}, set()

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
        if installed is not None and installed.match(node):
            base.setdefault(str(node), set()).add(cpv)
            return True
        if available is not None and available.match(node):
            external.setdefault(str(node), set()).add(cpv)
            return True
        if source is not None and source.match(node):
            source_matches.setdefault(str(node), set()).add(cpv)
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
    return unsatisfied, base, external, source_matches, seen


def main(path, exceptions=None, installed=None, available=None,
         write_available_path=None, source=None, source_tree=None,
         source_overlay=None, write_source_path=None, resolve_source=None,
         source_keywords="~amd64", source_overlay_keywords=None):
    fields = parse(pathlib.Path(path).read_text())
    if not fields:
        sys.exit(f"{path} 中没有任何 stanza")
    try:
        _installed_fields, have = read_snapshot(installed, "基础系统快照")
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"无法读取基础系统清单 {e}，无法判定缺失的依赖，本次不通过")
    try:
        if write_available_path:
            if not available:
                raise ValueError("未提供用于生成可用包快照的 binrepo 索引")
            source_text, available_fields = read_source_index(available)
            available_db = index_db(available_fields)
        else:
            available_fields, available_db = read_snapshot(
                available, "Gentoo binhost 可用包快照")
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"无法读取 Gentoo binhost 清单 {e}，本次不通过")

    unsatisfied, base, external, source_matches, seen = check(
        fields, have, available_db)
    if write_available_path:
        try:
            write_available(write_available_path, source_text, available_fields,
                            external)
            _selected, selected_db = read_snapshot(
                write_available_path, "Gentoo binhost 可用包快照")
        except (FileNotFoundError, OSError, ValueError) as e:
            sys.exit(f"无法生成 Gentoo binhost 可用包快照 {e}，本次不通过")
        available_db = selected_db
        unsatisfied, base, external, source_matches, seen = check(
            fields, have, available_db)
    try:
        if write_source_path:
            if not source_tree:
                raise ValueError("未提供用于生成源码快照的 Gentoo 仓库")
            write_source(write_source_path, source_tree, unsatisfied,
                         overlay=source_overlay, resolve=resolve_source,
                         accept_keywords=source_keywords,
                         overlay_keywords=source_overlay_keywords)
            _source_fields, source_db = read_snapshot(
                write_source_path, "Gentoo 源码可用包快照")
        else:
            _source_fields, source_db = read_snapshot(
                source, "Gentoo 源码可用包快照")
    except (FileNotFoundError, OSError, ValueError) as e:
        sys.exit(f"无法读取或生成 Gentoo 源码清单 {e}，本次不通过")
    if source_db is not None:
        unsatisfied, base, external, source_matches, seen = check(
            fields, have, available_db, source_db)
    known = read_exceptions(exceptions)

    accepted = {a for a in unsatisfied if a in known}
    stale = sorted((set(known) & seen) - set(unsatisfied))
    unsatisfied = {a: w for a, w in unsatisfied.items() if a not in known}

    if have is None:
        print("!! 未提供基础系统清单，索引之外的依赖一律计为未满足", file=sys.stderr)
    print(f"索引 {len(fields)} 个，{len(base)} 个原子由基础系统提供，"
          f"{len(external)} 个由 Gentoo binhost 提供，"
          f"{len(source_matches)} 个由源码仓库提供，"
          f"{len(accepted)} 个是已列出的例外")
    for atom in stale:
        print(f"!! 例外 {atom} 本次已能满足，应从 dep-exceptions.txt 删除",
              file=sys.stderr)
    if unsatisfied:
        print(f"!! {len(unsatisfied)} 个运行期依赖没有一个已发布版本满足，"
              f"基础系统、Gentoo binhost 与源码仓库也不提供", file=sys.stderr)
        for atom, who in sorted(unsatisfied.items())[:20]:
            print(f"   {atom}  <- {' '.join(sorted(who)[:3])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?",
                        default="/srv/pub/binpkgs/x86-64/Packages")
    parser.add_argument("--installed")
    parser.add_argument("--available")
    parser.add_argument("--write-available")
    parser.add_argument("--source")
    parser.add_argument("--source-tree")
    parser.add_argument("--source-overlay")
    parser.add_argument("--source-keywords", default="~amd64")
    parser.add_argument("--source-overlay-keywords")
    parser.add_argument("--write-source")
    options = parser.parse_args()
    sys.exit(main(options.path, installed=options.installed,
                  available=options.available,
                  write_available_path=options.write_available,
                  source=options.source, source_tree=options.source_tree,
                  source_overlay=options.source_overlay,
                  write_source_path=options.write_source,
                  source_keywords=options.source_keywords,
                  source_overlay_keywords=options.source_overlay_keywords))
