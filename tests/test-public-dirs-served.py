#!/usr/bin/env python3
"""Every public directory install.sh creates has to be served and listed.

A directory under /srv/pub with no nginx location falls through to the site
root, so a request for a file in it returns 404 or an unrelated file and
nothing reports a problem. Its location therefore has to serve files from
/srv/pub.

A directory URL negotiates: $gz_listing picks a text listing, the autoindex
page or the redirect to the file browser on gentoozh.org, and each form has an
internal location. A public directory whose location skips that rewrite answers
browsers and curl with nginx's stock page instead.

The prefix location only matches with the trailing slash, so the bare name
needs its own redirect or a shared link without the slash returns 404.
/files/<dir>/ is the file browser's name for /<dir>/, so it has to reach the
same listing.
"""

import pathlib
import re
import sys

from active_source import active_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
NGINX = ROOT / "nginx" / "mirror-common.inc"
MAPS = ROOT / "nginx" / "distfiles.conf"

LISTING = "rewrite ^ /_$gz_listing$uri last;"

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
    for line in active_text(INSTALL.read_text(), "shell").splitlines():
        if "install -dm" not in line:
            continue
        for path in re.findall(r"/srv/pub/([A-Za-z0-9._-]+)", line):
            out.add(path)
    return out


def strip_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def blocks(text):
    """Top-level location blocks: {header: body with whitespace collapsed}."""
    out = {}
    for m in re.finditer(r"^location ([^{\n]+?) \{", text, re.M):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out[m.group(1)] = " ".join(text[m.end():i - 1].split())
    return out


def listing_forms(text):
    """The values the $gz_listing map can produce."""
    m = re.search(r'map "[^"]*" \$gz_listing \{(.*?)\}', text, re.S)
    if not m:
        return set()
    return set(re.findall(r"\s(\w+);", m.group(1)))


nginx = blocks(strip_comments(NGINX.read_text()))
forms = listing_forms(strip_comments(MAPS.read_text()))

check("$gz_listing 给出文本、HTML 与浏览器三种形式", forms == {"txt", "html", "web"},
      "实际：" + " ".join(sorted(forms)))
for form in sorted(forms):
    body = nginx.get(f"^~ /_{form}/", "")
    check(f"/_{form}/ 是内部 location", "internal;" in body, body)
for form in sorted(forms - {"web"}):
    body = nginx.get(f"^~ /_{form}/", "")
    check(f"/_{form}/ 列出 /srv/pub", "alias /srv/pub/;" in body, body)
web = nginx.get("^~ /_web/", "")
check("/_web/ 把浏览器送到 gentoozh.org 的文件浏览器",
      "return 302 https://gentoozh.org$gz_prefix/files$gz_path_rel;" in web, web)

deep = nginx.get("^~ /files/", "")
check("/files/<目录>/ 改写到同一份清单",
      "rewrite ^/files(?<gz_dir>/.*/)$ /_$gz_listing$gz_dir last;" in deep, deep)

dirs = public_dirs()
check("读到了 install.sh 建立的公开目录", bool(dirs), str(dirs))
if not dirs:
    sys.exit(1)

for d in sorted(dirs):
    body = nginx.get(f"^~ /{d}/")
    check(f"nginx 提供 /{d}/", body is not None,
          "已有 location：" + " ".join(sorted(nginx)))
    body = body or ""
    check(f"/{d}/ 的文件取自 /srv/pub", "root /srv/pub;" in body, body)
    check(f"/{d}/ 下的目录按客户端协商清单形式",
          "location ~ /$ { " + LISTING + " }" in body, body)
    check(f"/{d} 不带斜杠时重定向到 /{d}/",
          nginx.get(f"= /{d}") == f"return 301 /{d}/;",
          str(nginx.get(f"= /{d}")))

print()
print("  公开目录：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
