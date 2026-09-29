#!/usr/bin/env python3
"""Check that each downstream mirror carries the newest files of the origin tree.

Mirrors send no CORS headers, so the file browser cannot ask them; this runs on the origin and writes
the answer to mirror-status.json, which the file browser reads. It sends HEAD requests for a bounded
set of sentinel paths taken from the local tree: the newest Live ISO release, the newest GIG-OS
files, the binpkg indexes and the newest distfiles. A file counts as missing when the mirror does not
serve it, serves another size, or serves an older copy than the origin's.
"""
import datetime
import email.utils
import json
import os
import pathlib
import queue
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

OUT = pathlib.Path(os.environ.get("OUT", "/srv/mirrors/mirror-status.json"))
ORIGIN = pathlib.Path(os.environ.get("ORIGIN", "/srv/pub"))
# The bases the site's mirror pickers use; MIRRORS="id=url id=url" replaces them.
MIRRORS = os.environ.get("MIRRORS") or " ".join([
    "cernet=https://mirrors.cernet.edu.cn/gentoo-zh",
    "nju=https://mirror.nju.edu.cn/gentoo-zh",
    "nyist=https://mirror.nyist.edu.cn/gentoo-zh",
    "hernet=https://mirrors.ha.edu.cn/gentoo-zh",
    "osuosl=https://ftp2.osuosl.org/pub/gentoo-zh",
])
TIMEOUT = float(os.environ.get("TIMEOUT", "10"))
DEADLINE = float(os.environ.get("DEADLINE", "300"))  # seconds for the whole run; later probes count as failed
WORKERS = 8
GIGOS_FILES = 5
DISTFILES = 20
MAX_PATHS = 40          # sentinels per mirror, so one run sends at most mirrors x (MAX_PATHS + 1) requests
MTIME_SLACK = 60        # seconds a mirror's Last-Modified may trail the origin's mtime


class KeepHead(urllib.request.HTTPRedirectHandler):
    # urllib turns a redirected HEAD into a GET, which would start sending an ISO's body.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.method = req.get_method()
        return new


OPENER = urllib.request.build_opener(KeepHead)


def files_under(top):
    out = []
    for root, dirs, names in os.walk(top):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if name.startswith("."):
                continue
            p = pathlib.Path(root, name)
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((st.st_mtime, p, st.st_size))
    return out


def sentinels():
    """[(origin-relative path, size, mtime)], at most MAX_PATHS."""
    picked = []

    def add(entries):
        for mtime, p, size in entries:
            picked.append(("/" + p.relative_to(ORIGIN).as_posix(), size, mtime))

    livecd = ORIGIN / "gentoo-cjk-livecd"
    releases = sorted(d for d in livecd.iterdir() if d.is_dir()) if livecd.is_dir() else []
    if releases:
        add(sorted(files_under(releases[-1]), key=lambda e: e[1]))
    add(sorted(files_under(ORIGIN / "gigos"), reverse=True)[:GIGOS_FILES])
    for index in ("binpkgs", "unstable/binpkgs"):
        for p in sorted((ORIGIN / index).glob("Packages")) + sorted((ORIGIN / index).glob("*/Packages")):
            st = p.stat()
            picked.append(("/" + p.relative_to(ORIGIN).as_posix(), st.st_size, st.st_mtime))
    add(sorted(files_under(ORIGIN / "distfiles"), reverse=True)[:DISTFILES])
    return picked[:MAX_PATHS]


def head(url):
    """(status, headers), or (None, None) when no usable HTTP answer came back."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with OPENER.open(req, timeout=TIMEOUT) as r:
            return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers
    except Exception:
        # A malformed answer (BadStatusLine, too many headers, TLS errors and the like) fails this probe only.
        return None, None


def current(path, size, mtime, base):
    status, headers = head(base + urllib.parse.quote(path))
    if status != 200:
        return False
    length = headers.get("Content-Length")
    if length is not None and length.isdigit() and int(length) != size:
        return False
    modified = headers.get("Last-Modified")
    if modified:
        try:
            when = email.utils.parsedate_to_datetime(modified)
        except (TypeError, ValueError):
            when = None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)   # a -0000 zone parses as naive
        if when is not None and when.timestamp() < mtime - MTIME_SLACK:
            return False
    return True


class Pool:
    """WORKERS daemon threads draining a queue of callables, which may add further jobs while they run.

    The threads are daemons, so a probe still hung at the deadline does not keep the process alive."""

    def __init__(self):
        self.todo = queue.Queue()
        self.pending = 0
        self.cond = threading.Condition()

    def add(self, job):
        with self.cond:
            self.pending += 1
        self.todo.put(job)

    def work(self, deadline):
        while time.monotonic() < deadline:
            try:
                job = self.todo.get(timeout=0.1)
            except queue.Empty:
                with self.cond:
                    if not self.pending:
                        return
                continue
            try:
                job()
            except Exception:
                pass    # the job's result stays unset, which counts as a failed probe
            with self.cond:
                self.pending -= 1
                self.cond.notify_all()

    def run(self, deadline):
        for _ in range(WORKERS):
            threading.Thread(target=self.work, args=(deadline,), daemon=True).start()
        with self.cond:
            self.cond.wait_for(lambda: not self.pending, timeout=max(0.0, deadline - time.monotonic()))


def check_all(mirrors, paths, deadline):
    """{id: status} for [(id, base)]. All probes share one pool and one deadline, so a slow mirror only holds
    the workers it occupies; a probe not done by the deadline counts as failed."""
    pool = Pool()
    up, good = {}, {}

    def probe_path(ident, base, s):
        good[ident, s[0]] = current(s[0], s[1], s[2], base)

    def probe_base(ident, base):
        # Any HTTP answer for the base, even 403 or 404, shows the mirror is up.
        if head(base + "/")[0] is None:
            return
        up[ident] = True
        for s in paths:
            pool.add(lambda s=s: probe_path(ident, base, s))

    for ident, base in mirrors:
        pool.add(lambda i=ident, b=base: probe_base(i, b))
    pool.run(deadline)
    up, good = dict(up), dict(good)     # probes still running past the deadline no longer count

    now = int(time.time())
    status = {}
    for ident, base in mirrors:
        reachable = up.get(ident, False)
        # A path that failed or ran past the deadline counts as missing: the file browser then keeps the
        # origin link for it. For an unreachable mirror that is every path.
        missing = [s[0] for s in paths if not (reachable and good.get((ident, s[0])))]
        status[ident] = {"base": base, "checked": now, "reachable": reachable,
                         "ok": reachable and not missing, "missing": missing}
    return status


def write(status):
    """Replace OUT atomically. The temporary file is created fresh in OUT's directory, which SITE_USER owns,
    so a name planted there (a symlink, say) is never followed by this root process."""
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, prefix="." + OUT.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"generated": int(time.time()), "mirrors": status},
                               ensure_ascii=False, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    deadline = time.monotonic() + DEADLINE
    mirrors = []
    for item in MIRRORS.split():
        ident, sep, base = item.partition("=")
        if not sep or not base.startswith(("http://", "https://")):
            print(f"!! 无法解析镜像项 {item!r}，应为 id=URL，已跳过", file=sys.stderr)
            continue
        mirrors.append((ident, base.rstrip("/")))
    if not mirrors:
        print(f"!! 没有可检查的镜像，保留原有的 {OUT}", file=sys.stderr)
        return 1

    try:
        paths = sentinels()
    except OSError as e:
        print(f"!! 无法读取源站目录 {ORIGIN}：{e}，保留原有的 {OUT}", file=sys.stderr)
        return 1
    if not paths:
        # Writing now would show every mirror in sync. The old file stays and the page drops it once stale.
        print(f"!! {ORIGIN} 下没有可检查的文件，保留原有的 {OUT}", file=sys.stderr)
        return 1

    status = check_all(mirrors, paths, deadline)
    if time.monotonic() >= deadline:
        print(f"!! 检查超过 {DEADLINE:g} 秒，未完成的请求按失败计", file=sys.stderr)
    for ident, s in status.items():
        if not s["reachable"]:
            print(f"!! {ident}：无法连接 {s['base']}", file=sys.stderr)
        elif s["missing"]:
            print(f"{ident}：{len(paths)} 个文件中缺少或过期 {len(s['missing'])} 个")
            for p in s["missing"][:5]:
                print(f"   {p}")
        else:
            print(f"{ident}：{len(paths)} 个文件均已同步")

    try:
        write(status)
    except OSError as e:
        print(f"!! 无法写出 {OUT}：{e}", file=sys.stderr)
        return 1
    print(f"已检查 {len(status)} 个镜像 -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
