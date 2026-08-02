#!/bin/bash

set -euo pipefail

DIST="${DIST:-/srv/pub/distfiles}"
OUT="${OUT:-/srv/mirrors/distfiles-index.json}"

find "${DIST}" -type f ! -name layout.conf ! -name README.txt -printf '%f\n' \
  | sort -u \
  | python3 -c 'import json,sys,time; json.dump({"generated": int(time.time()), "files": [l.strip() for l in sys.stdin if l.strip()]}, sys.stdout, ensure_ascii=False, separators=(",",":"))' \
  > "${OUT}.new"

mv -f "${OUT}.new" "${OUT}"

n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["files"]))' "${OUT}")

STATUS="${STATUS:-/srv/mirrors/distfiles-status.json}"
printf '{"files":%s,"generated":%s}\n' "${n}" "$(date +%s)" > "${STATUS}.new"
mv -f "${STATUS}.new" "${STATUS}"

echo "${n} 个文件 -> ${OUT}"
