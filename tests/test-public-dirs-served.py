#!/usr/bin/env python3
"""Every public directory install.sh creates has to be served and described.

A directory under /srv/pub with no nginx location falls through to the site
root, so a request for a file in it returns the home page with status 200 and
nothing reports a problem. The file browser reads the same tree from /_ls/, so
an entry with no description shows up there unlabelled.

The prefix location only matches with the trailing slash, so the bare name
needs its own redirect or a shared link without the slash returns 404. The 404
page lists what is available, so a directory missing from it is invisible to
anyone who lands there.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
NGINX = ROOT / "nginx" / "mirror-common.inc"
APP = ROOT / "site" / "_app.html"
NOTFOUND = ROOT / "site" / "404.html"

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def public_dirs():
    """Top-level names install.sh creates under /srv/pub."""
    out = set()
    for line in INSTALL.read_text().splitlines():
        if "install -dm" not in line:
            continue
        for path in re.findall(r"/srv/pub/([A-Za-z0-9._-]+)", line):
            out.add(path)
    return out


nginx = NGINX.read_text()
app = APP.read_text()
notfound = NOTFOUND.read_text()
listed = set(re.findall(r'href="(/[A-Za-z0-9._/-]*)"', notfound))
served = set(re.findall(r"^location \^~ /([A-Za-z0-9._-]+)/ \{", nginx, re.M))
redirected = set(re.findall(
    r"^location = /([A-Za-z0-9._-]+) \{ return 301 /\1/; \}", nginx, re.M))
described = set(re.findall(r"^  '([A-Za-z0-9._-]+)': \{", app, re.M))

dirs = public_dirs()
check("读到了 install.sh 建立的公开目录", bool(dirs), str(dirs))
if not dirs:
    sys.exit(1)

for d in sorted(dirs):
    check(f"nginx 提供 /{d}/", d in served,
          "已有 location：" + " ".join(sorted(served)))
    check(f"文件浏览器为 {d} 写了说明", d in described,
          "已有说明：" + " ".join(sorted(described)))
    check(f"/{d} 不带斜杠时重定向到 /{d}/", d in redirected,
          "已有重定向：" + " ".join(sorted(redirected)))
    check(f"404 页把 {d} 列进可用资源", any(f"/{d}/" in h for h in listed),
          "已列出：" + " ".join(sorted(listed)))

print()
print("  公开目录：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
