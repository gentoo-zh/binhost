#!/bin/bash
# Export the distfile names actually present on the mirror as a JSON array, so
# the package list page can tell what is complete.
#
# The files sit in two levels of hash directories; walking them from the page
# would take hundreds of requests, so it is done once here. Runs after each
# sync.

set -euo pipefail

DIST="${DIST:-/srv/pub/distfiles}"
OUT="${OUT:-/srv/mirrors/distfiles-index.json}"

# 两个标记文件都不是 distfile。原来只排 layout.conf，README.txt 被算进去，
# 站上的数字比实际多一个，而对帐脚本两个都排，两边长期差一。
find "${DIST}" -type f ! -name layout.conf ! -name README.txt -printf '%f\n' \
  | sort -u \
  | python3 -c 'import json,sys,time; json.dump({"generated": int(time.time()), "files": [l.strip() for l in sys.stdin if l.strip()]}, sys.stdout, ensure_ascii=False, separators=(",",":"))' \
  > "${OUT}.new"

mv -f "${OUT}.new" "${OUT}"

n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["files"]))' "${OUT}")

# The front page needs only the count and the time. Reading the index above for
# that would transfer a thousand-odd filenames.
STATUS="${STATUS:-/srv/mirrors/distfiles-status.json}"
printf '{"files":%s,"generated":%s}\n' "${n}" "$(date +%s)" > "${STATUS}.new"
mv -f "${STATUS}.new" "${STATUS}"

echo "${n} 个文件 -> ${OUT}"
