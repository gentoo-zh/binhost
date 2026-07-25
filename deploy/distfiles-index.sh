#!/bin/bash
# 把镜像上实际存在的 distfile 文件名导出成一个 JSON 数组，供包列表页判断齐全与否。
#
# 文件散在两级哈希目录里，页面自己遍历要几百个请求；这里在服务器上一次算完。
# 每次同步之后跑。

set -euo pipefail

DIST="${DIST:-/srv/pub/distfiles}"
OUT="${OUT:-/srv/mirrors/distfiles-index.json}"

find "${DIST}" -type f ! -name layout.conf -printf '%f\n' \
  | sort -u \
  | python3 -c 'import json,sys,time; json.dump({"generated": int(time.time()), "files": [l.strip() for l in sys.stdin if l.strip()]}, sys.stdout, ensure_ascii=False, separators=(",",":"))' \
  > "${OUT}.new"

mv -f "${OUT}.new" "${OUT}"

n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["files"]))' "${OUT}")

# 首页只需要数量与时间。让它去读上面那份索引，一次要传一千多个文件名。
STATUS="${STATUS:-/srv/mirrors/distfiles-status.json}"
printf '{"files":%s,"generated":%s}\n' "${n}" "$(date +%s)" > "${STATUS}.new"
mv -f "${STATUS}.new" "${STATUS}"

echo "${n} 个文件 -> ${OUT}"
