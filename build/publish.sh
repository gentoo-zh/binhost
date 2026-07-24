#!/bin/bash
# Publish a staged generation to the mirror.
#
# 顺序是有意的，任何一步中断都不能让客户端读到一个指向不存在文件的索引：
#   1. 先传包体，不删任何文件——此时旧索引仍然有效，指向的文件都还在
#   2. 索引写成临时名再 rename 换入，rename 在同一文件系统上是原子的
#   3. 最后才删索引不再提到的文件
#
# 顺序颠倒会让客户端在中间那段时间拿到 404。

set -euo pipefail

# 主体放进函数：bash 按字节偏移边读边执行，脚本在运行中被替换会让执行路径错乱。
main() {
TAG="${TAG:-x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/binpkgs/${TAG}}"

[[ -f ${STAGE}/Packages ]] || { echo "nothing staged at ${STAGE}" >&2; exit 1; }

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${STAGE}/Packages")
(( ${#paths[@]} )) || { echo "index lists no packages" >&2; exit 1; }

echo ">>> 发布 ${#paths[@]} 个包到 ${REMOTE}:${REMOTE_ROOT}"

# shellcheck disable=SC2029  # 路径要在本地展开成具体值
ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}"

# --- 1. 包体 ------------------------------------------------------------------
# 按索引里的清单传，不是整个目录：暂存区里可能有上一代留下的文件。
# 不加 --delete，删除留到索引换好之后。
printf '%s\n' "${paths[@]}" |
    rsync -a --info=stats2 --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/" |
    grep -E "files transferred|Total transferred file size" | sed 's/^/    /'

# --- 2. 索引 ------------------------------------------------------------------
rsync -a "${STAGE}/Packages" "${REMOTE}:${REMOTE_ROOT}/.Packages.new"
rsync -a "${STAGE}/Packages.gz" "${REMOTE}:${REMOTE_ROOT}/.Packages.gz.new"
# shellcheck disable=SC2029  # 同上
ssh "${REMOTE}" "cd ${REMOTE_ROOT} && \
    mv -f .Packages.new Packages && \
    mv -f .Packages.gz.new Packages.gz"

# --- 2b. 给站点用的两个数字 ----------------------------------------------------
# 首页只需要包数和时间。让它去读索引时浏览器会带 Accept-Encoding: gzip，
# nginx 就把 Range 忽略掉整份发过来——每次打开首页传 39 KB 只为读两个数。
ts=$(awk '/^TIMESTAMP: /{print $2; exit}' "${STAGE}/Packages")
n=$(awk '/^PACKAGES: /{print $2; exit}' "${STAGE}/Packages")
# shellcheck disable=SC2029  # REMOTE_ROOT 就是要在本地展开成具体路径
printf '{"packages":%s,"generated":%s}\n' "${n:-0}" "${ts:-0}" |
    ssh "${REMOTE}" "cat > ${REMOTE_ROOT}/.status.json.new &&
                     mv -f ${REMOTE_ROOT}/.status.json.new ${REMOTE_ROOT}/status.json"

# --- 3. 清理索引不再提到的文件 -------------------------------------------------
# 用索引本身当清单，而不是比对暂存区：索引才是对外的事实。
# 删完可能留下空目录，一个包被完全移除时就会这样。
# shellcheck disable=SC2029  # 同上
retired=$(printf '%s\n' "${paths[@]}" | ssh "${REMOTE}" "
    cat > /tmp/binhost-keep.txt
    # 保留清单为空时 grep -vxF -f 会匹配所有行，下面那句 rm 就会清空整个仓库。
    # 传输中断、管道出错都可能让它是空的，所以在删之前挡住。
    [ -s /tmp/binhost-keep.txt ] || { echo '保留清单为空，中止清理' >&2; exit 1; }
    cd ${REMOTE_ROOT} || exit 1
    find . -name '*.gpkg.tar' -printf '%P\n' |
        grep -vxF -f /tmp/binhost-keep.txt |
        tee /tmp/binhost-retire.txt |
        xargs -r rm -f
    find . -mindepth 1 -type d -empty -delete
    wc -l < /tmp/binhost-retire.txt
    rm -f /tmp/binhost-keep.txt /tmp/binhost-retire.txt")

echo ">>> 已发布 ${#paths[@]} 个，清理 ${retired} 个"

}

main "$@"
