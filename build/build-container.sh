#!/bin/bash
# Build the overlay's binary packages and stage them for publication.
#
# The build runs in a container, not on the build machine, because the machine
# has CFLAGS="-O2 -pipe -march=native" on a Skylake-SP Xeon. Portage does not
# compare CFLAGS when it decides whether a binary package is usable, so those
# packages would reach users on older CPUs and die on an illegal instruction,
# with nothing in portage's output pointing back here.
#
# Layout follows the official binhost: split by CPU baseline, not init system.
# Only a handful of the listed packages mention `systemd` in IUSE.

set -euo pipefail

# 主体放进函数，最后一行才调用。bash 是按字节偏移边读边执行的，脚本在运行中
# 被替换（例如 rsync 部署一次新版本）会让它从新文件的同一偏移继续读，
# 执行路径因此错乱。包成函数之后 bash 先整体解析，运行中改文件不影响本次执行。
main() {
TAG="${TAG:-x86-64}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
BASE_MAX_AGE_DAYS="${BASE_MAX_AGE_DAYS:-7}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${TAG}}"
# Where portage lands what it fetches from the official binhost. The path comes
# from binrepos.conf inside the image; mounting it keeps the download across
# runs. Without the mount the container starts with an empty one and pulls the
# same ~1 GB of ::gentoo binaries again every round.
GENTOO_BINPKGS="${GENTOO_BINPKGS:-/var/cache/binhost/gentoo}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/${TAG}}"
LIST="${LIST:-$(dirname "$0")/packages.txt}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
JOBS="${JOBS:-8}"
MAKEOPTS="${MAKEOPTS:--j12}"

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }

# 两轮同时跑会一起写同一个 PKGDIR 和 STAGE。锁放在这里而不是调用方，
# 是因为手工调、定时器调、重跑某几个包，走的都是这一层。
#
# 锁文件跟着 STAGE 走，不放 /var/lock：构建以普通用户执行，对那个目录没有写入权限。
LOCK="${LOCK:-$(dirname "${STAGE}")/build.lock}"
mkdir -p "$(dirname "${LOCK}")"
exec 9>"${LOCK}"
flock -n 9 || die "另一轮构建正在进行（${LOCK}）"

[[ -s ${LIST} ]] || die "package list not found or empty: ${LIST}"
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset; unsigned packages are not publishable"
for p in "${OVERLAY}" "${TREE}" "${DISTDIR}" "${SIGNING_GNUPGHOME}"; do
    [[ -d ${p} ]] || die "missing: ${p}"
done

# --- base image --------------------------------------------------------------
# Refreshed on age rather than every run: aligning @world takes over an hour
# and the tree does not move far in a week.

created=$(${DOCKER} image inspect "${BASE}" --format '{{.Created}}' 2>/dev/null || true)
stale=1
if [[ -n ${created} ]]; then
    age_days=$(( ( $(date +%s) - $(date -d "${created}" +%s) ) / 86400 ))
    (( age_days < BASE_MAX_AGE_DAYS )) && stale=0
    echo ">>> base image ${BASE} is ${age_days}d old"
fi
if (( stale )); then
    echo ">>> refreshing base image"
    TAG="${TAG}" BASE="${BASE}" SIGNING_KEY="${SIGNING_KEY}" \
    TREE="${TREE}" OVERLAY="${OVERLAY}" DISTDIR="${DISTDIR}" PKGDIR="${PKGDIR}" \
    SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME}" JOBS="${JOBS}" MAKEOPTS="${MAKEOPTS}" \
        "$(dirname "$0")/base-image.sh"
fi

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" \
    "${PKGDIR}" "$(dirname "${STAGE}")" "${LOGDIR}" "${GENTOO_BINPKGS}"
rm -f "${LOGDIR}"/*.log "${LOGDIR}"/failed.txt

# 磁盘写满或构建被打断会在缓存里留下 0 字节的 gpkg。portage 每轮都要为它们
# 报一次 Invalid binary package，然后当成没有缓存重新编一遍。实测留了 70 个。
empty=$(find "${PKGDIR}" -name '*.gpkg.tar' -size 0 -print -delete | wc -l)
(( empty )) && echo ">>> 清掉 ${empty} 个 0 字节的缓存包" 

# --- build -------------------------------------------------------------------

echo ">>> building from ${BASE}"

${DOCKER} run --rm -i --privileged \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${GENTOO_BINPKGS}:/var/cache/binhost/gentoo" \
    -v "${LIST}:/tmp/packages.txt:ro" \
    -v "${SIGNING_GNUPGHOME}:/root/.gnupg" \
    -v "${LOGDIR}:/var/log/binhost" \
    -e "SIGNING_KEY=${SIGNING_KEY}" \
    -e "OVERLAY_REV=$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    "${BASE}" /bin/bash -euo pipefail -s <<'INNER'

# The signing command is flock /run/lock/portage-binpkg-gpg.lock ...; the image
# has no /run/lock.
mkdir -p /run/lock

# Signing belongs to publishing, not to the environment, so it is configured
# here rather than baked into the base image -- that keeps the image usable by
# anyone who does not hold the key.
#
# binpkg-signing embeds the signature inside the .gpkg.tar, which is the only
# form portage's verify-signature checks. gpg-keepalive is needed because
# gpg-agent drops cached credentials after two hours and a full run is longer
# than that.
cat >> /etc/portage/make.conf <<EOF
FEATURES="\${FEATURES} binpkg-signing gpg-keepalive"
BINPKG_GPG_SIGNING_KEY="${SIGNING_KEY}"
BINPKG_GPG_SIGNING_GPG_HOME="/root/.gnupg"
EOF

# 依赖上要开的 USE。全量跑第一次时这些包全都失败在 autounmask，portage 只
# 是拒绝自动改配置，ebuild 本身没问题——每一条都是某个 ebuild 明写的依赖。
#
# 加在依赖上，不加在我们自己的包上：我们的包按默认 USE 构建，用户拿到的才
# 和自己 emerge 出来的一致。
mkdir -p /etc/portage/package.use
cat > /etc/portage/package.use/binhost-deps <<'EOF'
dev-libs/marisa        python      # app-i18n/fcitx-kkc
sys-libs/minizip-ng    compat      # app-text/goldendict
sys-libs/libsolv       conda       # dev-util/mamba, dev-python/conda
dev-util/mamba         python      # dev-python/conda
app-i18n/opencc        python      # dev-python/mw2fcitx
media-video/pipewire   gstreamer   # net-misc/rustdesk
EOF

mapfile -t atoms < <(grep -E '^[a-z0-9-]+/[A-Za-z0-9._+-]+$' /tmp/packages.txt)
echo ">>> ${#atoms[@]} packages"

# --changed-use：依赖的 USE 变了就重建，不然会把 PKGDIR 里按旧 USE 编的那份
# 原样再发一遍。ebuild 内容改了但版本未动时 portage 无法察觉，那种要靠 revbump。
EMERGE=(emerge --usepkg --changed-use --with-bdeps=y --quiet-build)

# 先整体来一次。portage 解析一遍就知道谁要重编，实测 183 个包解析 171 秒，
# 而逐包跑要各解析一次，中位数 19 秒、合计一个半小时——那一个半小时算的是
# 同一棵依赖树，算 183 遍。
#
# 整体跑的代价是第一个解不开的依赖会中止全部，所以它失败时退回逐包，保住
# 「一个坏包只损失一个包」和每包一份日志。正常情况下退回不会发生。
echo "::: 整体解析"
failed=()
if "${EMERGE[@]}" "${atoms[@]}" > /var/log/binhost/whole.log 2>&1; then
    echo ">>> 整体一次完成，未逐包重跑"
    rm -f /var/log/binhost/whole.log
else
    echo "!!! 整体失败，退回逐包（每包一份日志）"
    tail -5 /var/log/binhost/whole.log | sed 's/^/    /'
    for atom in "${atoms[@]}"; do
        echo "::: ${atom}"
        log=/var/log/binhost/${atom//\//_}.log
        if ! "${EMERGE[@]}" "${atom}" > "${log}" 2>&1; then
            failed+=("${atom}")
            echo "${atom}" >> /var/log/binhost/failed.txt
            tail -3 "${log}" | sed 's/^/    /'
        else
            rm -f "${log}"    # 成功的不留，否则一百多份日志里找不到重点
        fi
    done
fi

emaint binhost --fix

if (( ${#failed[@]} )); then
    printf '!!! %d failed:\n' "${#failed[@]}"
    printf '      %s\n' "${failed[@]}"
fi
INNER

# --- stage -------------------------------------------------------------------
# PKGDIR also holds every dependency built or fetched along the way. Those are
# not ours to publish and of no use to our users.

rm -rf "${STAGE}.new"
install -dm755 "${STAGE}.new"

PKGDIR="${PKGDIR}" STAGE="${STAGE}.new" \
OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
python3 - <<'PY'
import os, re, shutil, sys, time

pkgdir, stage = (os.environ[k] for k in ("PKGDIR", "STAGE"))
stanzas = open(os.path.join(pkgdir, "Packages")).read().split("\n\n")
header, keep, skipped = stanzas[0], [], 0
best = {}   # cpv -> (build_id, fields, stanza)

for s in stanzas[1:]:
    if not s.strip():
        continue
    f = dict(re.findall(r"^(\w+): (.*)$", s, re.M))
    cpv = f.get("CPV")
    if not cpv:
        continue
    # 按 REPO 判断，不按 overlay 里有没有同名目录。目录判断挡不住两种情况：
    # overlay 只有 -9999 而实际编的是 ::gentoo 的发行版（fcitx、librime 这些），
    # 以及 overlay 的版本比 ::gentoo 低、portage 选了 ::gentoo 那个
    # （libdatrie、libthai）。两种情况交付的都是 ::gentoo 的构建物。
    if f.get("REPO") != "gentoo-zh":
        skipped += 1
        continue
    # ACCEPT_LICENSE should have stopped these at build time. Check again
    # rather than let one gate stand between us and a licensing problem.
    if "bindist" in f.get("RESTRICT", ""):
        sys.exit(f"refusing to stage RESTRICT=bindist package: {cpv}")
    # binpkg-multi-instance 会给同一版本的每次重建一个新的 BUILD_ID，旧的留在
    # PKGDIR 的索引里。两个都发出去会让索引里同一个 CPV 有两条，清理段也删不掉
    # （它按索引判断该留什么）。只留 BUILD_ID 最大的那个实例。
    bid = int(f.get("BUILD_ID", 0))
    prev = best.get(cpv)
    if prev and prev[0] >= bid:
        skipped += 1
        continue
    if prev:
        skipped += 1
    best[cpv] = (bid, f, s)

for bid, f, s in best.values():
    src = os.path.join(pkgdir, f["PATH"])
    dst = os.path.join(stage, f["PATH"])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(src, dst)
    keep.append(s)

# 头部照抄会让 PACKAGES 仍是构建缓存里的总数（含依赖），比实际发布的多数倍。
# TIMESTAMP 同理，要的是这一代的时间而不是缓存上次写入的时间。
header = re.sub(r"^PACKAGES: .*$", f"PACKAGES: {len(keep)}", header, flags=re.M)
header = re.sub(r"^TIMESTAMP: .*$", f"TIMESTAMP: {int(time.time())}", header, flags=re.M)

# 这批包建自 overlay 的哪个提交。portage 只在自己 sync 过仓库时才填这一项，
# 我们是只读挂载，它写出来的是空的 {}。补上之后索引能自证建自哪一版，
# 版本核对也有了准确的基准——不然构建期间 overlay 又动了就会误报。
rev = os.environ.get("OVERLAY_REV", "")
if rev:
    header = re.sub(r"^REPO_REVISIONS: .*$",
                    'REPO_REVISIONS: {"gentoo-zh": "%s"}' % rev, header, flags=re.M)

open(os.path.join(stage, "Packages"), "w").write(
    header + "\n\n" + "\n\n".join(keep) + "\n")
print(f">>> staged {len(keep)}, skipped {skipped} not from the overlay")
PY

# Packages are already signed -- portage did that during the build. Only the
# gzipped index is left; the official binhost ships Packages and Packages.gz
# and nothing else.
gzip -kf "${STAGE}.new/Packages"

rm -rf "${STAGE}.old"
[[ -d ${STAGE} ]] && mv "${STAGE}" "${STAGE}.old"
mv "${STAGE}.new" "${STAGE}"
echo ">>> staged at ${STAGE} (previous generation kept at ${STAGE}.old)"

# --- 失败分类 -----------------------------------------------------------------
if [[ -s ${LOGDIR}/failed.txt ]]; then
    python3 "$(dirname "$0")/classify-failures.py" "${LOGDIR}" | tee "${LOGDIR}/report.txt"
fi

}

main "$@"
