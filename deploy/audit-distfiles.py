#!/usr/bin/env python3

import contextlib
import errno
import fcntl
import os
import pathlib
import json
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "build")]
from ebuilds import pinned_portdbapi                       # noqa: E402
from portage.dep import use_reduce                         # noqa: E402
from portage.exception import PortageException             # noqa: E402


class LedgerError(Exception):
    pass


@contextlib.contextmanager
def locked(path):
    """Hold an exclusive lock beside path for a whole read-modify-write.

    daily.sh already serialises the scheduled run, so this is what keeps a
    hand-run of this script from racing it and losing a reservation. Without
    the lock two runs can each read the same ledger and each spend the whole
    budget, so failing to take it has to stop the round rather than proceed.
    """
    lock = pathlib.Path(f"{path}.lock")
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)
    except OSError as e:
        raise LedgerError(f"无法建立 {lock}，本轮不做任何清理：{e}") from e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".new")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def carriable_names(uri_map, restrict):
    """(names we may carry, whether RESTRICT took any URI away), or None.

    Same rules as portage's _emirrordist: RESTRICT is reduced with the same
    flat, matchnone arguments, so only unconditional restrictions apply and
    demo? ( mirror ) does not stop us carrying the file. fetch restriction
    implies mirror restriction, a mirror+ URI lifts both for itself, fetch+
    lifts only the fetch one, and a file stays carriable while any one of its
    URIs survives. Portage's mirror:// exemption list is not configured on
    this host, so it is not applied here either.

    The second value separates the two ways a name can end up with no usable
    URI. A restriction means we must not carry it. No URI at all, as a bare
    SRC_URI name declares, means nobody can fetch it, which is not a reason to
    take anything down.
    """
    try:
        tokens = frozenset(use_reduce(restrict, flat=True, matchnone=True))
    except PortageException:
        return None
    no_fetch = "fetch" in tokens
    no_mirror = no_fetch or "mirror" in tokens
    out = set()
    for name, uris in uri_map.items():
        for uri in uris:
            lifts_mirror = uri.startswith("mirror+")
            lifts_fetch = lifts_mirror or uri.startswith("fetch+")
            if no_fetch and not lifts_fetch:
                continue
            if no_mirror and not lifts_mirror:
                continue
            out.add(name)
            break
    return out, no_mirror


def portage_aux(overlay, tree=None):
    """cp -> [(cpv, {distfile: [uri]}, RESTRICT)] from Portage's own metadata.

    The fetch map is what keeps each URI attached to the name it writes, which
    is what the per-URI fetch+ and mirror+ prefixes act on.

    Every query names the overlay. Three packages currently exist in both
    trees, and without the tree an ebuild from ::gentoo decides what happens
    to a file the overlay's Manifest declared.
    """
    db = pinned_portdbapi(overlay, tree) if tree else pinned_portdbapi(overlay)
    tree = str(overlay)

    def aux(cp):
        for cpv in db.cp_list(cp, mytree=tree):
            try:
                restrict = db.aux_get(cpv, ["RESTRICT"], mytree=tree)[0]
                uri_map = db.getFetchMap(cpv, mytree=tree)
            except Exception:                              # noqa: BLE001
                yield cpv, None, None
                continue
            yield cpv, uri_map, restrict
    return aux


def scan(overlay, aux=None):
    """distfile -> [(cp, blocked)], the undecided ones and the unfetchable ones.

    Attribution comes from each CPV's fetch map, so a shared file, a renamed
    download or a name without a version in it all land on the right package.
    When Portage metadata cannot be read the file goes into the undecided set
    and nothing will delete it.
    """
    users = {}
    unsure = set()
    unfetchable = set()
    if aux is None:
        try:
            aux = portage_aux(overlay)
        except Exception as e:                             # noqa: BLE001
            print(f"!! 无法读取 Portage metadata：{e}", file=sys.stderr)
            return {}, set(), set()

    for man in overlay.glob("*/*/Manifest"):
        d = man.parent
        cp = str(d.relative_to(overlay))
        declared = set()
        for line in man.read_text(errors="replace").splitlines():
            if line.startswith("DIST "):
                declared.add(line.split()[1])

        seen = set()
        for cpv, uri_map, restrict in aux(cp):
            if uri_map is None:
                unsure.update(declared)
                continue
            names = set(uri_map) & declared
            decided = carriable_names(uri_map, restrict)
            if decided is None:
                unsure.update(names)
                continue
            carriable, restricted = decided
            for name in names:
                blocked = name not in carriable and restricted
                if name not in carriable and not restricted:
                    unfetchable.add(name)
                entry = (cp, blocked)
                if entry not in users.setdefault(name, []):
                    users[name].append(entry)
                seen.add(name)

        for name in declared - seen:
            unsure.add(name)
            if (cp, True) not in users.setdefault(name, []):
                users[name].append((cp, True))
    return users, unsure, unfetchable


GRACE_SECONDS = 7 * 24 * 3600
STATE = "/var/lib/emirrordist/orphans.json"

RECYCLE = "/var/lib/emirrordist/recycle"

MAX_REAP_SHARE = 1 / 3

MIN_RESTRICTED_TO_DOUBT = 20

MIN_REAP_BUDGET = 5

LEDGER = "/var/lib/emirrordist/reaped.json"
WINDOW_HOURS = 24

MARKERS = {"layout.conf", "README.txt"}


def recent_deletions(add_count, now=None):
    now = int(time.time()) if now is None else now
    f = pathlib.Path(LEDGER)
    with locked(f):
        try:
            rows = json.loads(f.read_text())
        except FileNotFoundError:
            rows = []
        except (OSError, ValueError) as e:
            raise LedgerError(f"{f} 无法读取：{e}") from e
        if not isinstance(rows, list):
            raise LedgerError(f"{f} 内容不是清单")
        rows = [r for r in rows if now - r[0] < WINDOW_HOURS * 3600]
        if add_count:
            rows.append([now, add_count])
        try:
            write_atomic(f, json.dumps(rows))
        except OSError as e:
            raise LedgerError(f"{f} 无法写入：{e}") from e
    return sum(n for _, n in rows)


def recycle(path):
    bin_ = pathlib.Path(RECYCLE)
    try:
        bin_.mkdir(parents=True, exist_ok=True)
        dst = bin_ / path.name
        n = 0
        while dst.exists():
            n += 1
            dst = bin_ / f"{path.name}.{n}"
        try:
            path.rename(dst)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            shutil.copy2(path, dst)
            path.unlink()
        return True
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法回收 {path.name}: {e}", file=sys.stderr)
        return False


def reap(orphan, paths, grace=None, budget=None):
    grace = GRACE_SECONDS if grace is None else grace

    state = pathlib.Path(STATE)
    try:
        seen = json.loads(state.read_text())
    except (OSError, ValueError):
        seen = {}

    now = int(time.time())
    seen = {f: t for f, t in seen.items() if f in orphan}
    deleted = []
    failed = []
    held = 0
    for f in orphan:
        first = seen.setdefault(f, now)
        if now - first < grace:
            continue
        path = paths.get(f)
        if path is None:
            continue
        if budget is not None and len(deleted) >= budget:
            held += 1
            continue
        if recycle(path):
            deleted.append(f)
        else:
            failed.append(f)
    if held:
        print(f"!! 达到额度上限，本轮保留 {held} 个未清理", file=sys.stderr)
    for f in deleted:
        seen.pop(f, None)

    try:
        write_atomic(state, json.dumps(seen, indent=1, sort_keys=True))
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法写入 {state}: {e}", file=sys.stderr)
        failed.append(str(state))
    return deleted, failed


def main(overlay, dest, aux=None):
    overlay, dest = pathlib.Path(overlay), pathlib.Path(dest)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"不是 ebuild 仓库：{overlay}")

    users, unsure, unfetchable = scan(overlay, aux)
    paths = {p.name: p for p in dest.rglob("*") if p.is_file() and p.name not in MARKERS}
    have = set(paths)

    # One consumer forbidding it is enough: attribution is exact, so the
    # aggregate has to be the conservative one.
    mirrorable = {f for f, us in users.items()
                  if us and all(not r for _, r in us)} - unfetchable
    never = {f for f, us in users.items() if any(r for _, r in us)}

    mirrorable -= unsure
    never -= unsure

    missing = sorted(mirrorable - have)
    extra = sorted(never & have)
    orphan = sorted(have - set(users))

    refused = ""
    if not users:
        refused = f"overlay 一个 Manifest 都没有读到，{overlay} 不完整"
    elif have and len(orphan) > len(have) * MAX_REAP_SHARE:
        refused = (f"本轮 {len(orphan)}/{len(have)} 个文件无人引用，"
                   f"超过 {MAX_REAP_SHARE:.0%}")

    spent, budget, reserved = 0, 0, 0
    if not refused:
        try:
            spent = recent_deletions(0)
        except LedgerError as e:
            refused = f"{e}，跨轮预算无依据"
        else:
            budget = max(0, max(MIN_REAP_BUDGET,
                                int(len(have) * MAX_REAP_SHARE)) - spent)

    restricted, restricted_failed = [], []
    too_many = (len(extra) > MIN_RESTRICTED_TO_DOUBT
                and len(extra) > len(have) * MAX_REAP_SHARE)
    if too_many:
        print(f"!! 本轮 {len(extra)}/{len(have)} 个文件被标为禁止镜像，"
              f"超过 {MAX_REAP_SHARE:.0%}，没有清理", file=sys.stderr)

    want = len(orphan) + (0 if too_many else len(extra))
    if not refused and budget:
        reserved = min(budget, want)
        try:
            recent_deletions(reserved)
        except LedgerError as e:
            refused = f"{e}，额度无法预留"
            reserved = 0

    if not refused and not too_many:
        for f in extra:
            if len(restricted) >= reserved:
                print(f"!! 达到额度上限，{len(extra) - len(restricted)} 个禁止镜像的"
                      f"文件本轮未清理", file=sys.stderr)
                break
            path = paths.get(f)
            if path is None:
                continue
            (restricted if recycle(path) else restricted_failed).append(f)

    left = max(0, budget - len(restricted))
    deleted, failed = ([], []) if refused else reap(orphan, paths, budget=left)

    recent = spent + reserved
    actually = len(deleted) + len(restricted)
    if reserved != actually:
        try:
            recent = recent_deletions(actually - reserved)
        except LedgerError as e:
            print(f"!! 帐本未能核销预留额度：{e}", file=sys.stderr)
            failed = failed + deleted
    if not refused and budget == 0 and orphan:
        refused = (f"最近 {WINDOW_HOURS} 小时累计清理 {spent} 个，"
                   f"已达镜像的 {MAX_REAP_SHARE:.0%}，本轮未清理")

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}，"
          f"无法判定 {len(unsure)}")
    if unsure:
        print(f"!! {len(unsure)} 个文件无法判定可否公开：Portage metadata 读取失败、"
              f"RESTRICT 解析失败，或 Manifest 里的条目不属于任何一个版本；"
              f"本轮既不清理也不当作可公开", file=sys.stderr)
        for f in sorted(unsure)[:10]:
            print(f"   无法判定 {f}  <- {[p for p, _ in users.get(f, [])]}", file=sys.stderr)
    print(f"镜像上 {len(have)}，缺 {len(missing)}，禁止镜像 {len(extra)}，"
          f"已无人引用 {len(orphan)}，本轮清理 {len(deleted) + len(restricted)}"
          f"（其中禁止镜像 {len(restricted)}）")
    if restricted_failed:
        print(f"!! {len(restricted_failed)} 个禁止镜像的文件回收失败，仍可公开存取",
              file=sys.stderr)
    if failed:
        print(f"!! {len(failed)} 个回收失败，本轮清理未完成", file=sys.stderr)
    if refused:
        print(f"!! 拒绝清理：{refused}", file=sys.stderr)

    for f in missing[:20]:
        print(f"  缺 {f}  <- {[p for p, _ in users[f]]}")
    for f in extra[:20]:
        print(f"  多 {f}  <- {[p for p, _ in users[f]]}"
              f"（至少一个引用方 RESTRICT 禁止镜像或禁止抓取）")
    for f in deleted[:20]:
        print(f"  清理 {f}")

    return 1 if (missing or refused or failed or restricted_failed or too_many) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
