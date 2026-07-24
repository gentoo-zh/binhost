#!/bin/bash
# Build the base image the package builds run in.
#
# A fresh stage3 is a snapshot from release day: its installed set is older
# than the tree, which produces slot conflicts and links new packages against
# old libraries. Aligning it with @world fixes that but costs over an hour,
# and a throwaway container pays that cost on every run.
#
# So the alignment happens here once and is committed to an image. Refresh it
# when it is older than BASE_MAX_AGE_DAYS; the rest of the time package builds
# start from an already-current root.

set -euo pipefail

TAG="${TAG:-x86-64}"
STAGE3="${STAGE3:-gentoo/stage3:amd64-desktop-openrc}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
TREE="${TREE:-/var/db/repos/gentoo}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${TAG}}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
MAKEOPTS="${MAKEOPTS:--j12}"
JOBS="${JOBS:-8}"

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset"
for p in "${TREE}" "${OVERLAY}" "${DISTDIR}" "${SIGNING_GNUPGHOME}"; do
    [[ -d ${p} ]] || die "missing: ${p}"
done

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" "${PKGDIR}"

container="binhost-base-build-${TAG}"
${DOCKER} rm -f "${container}" >/dev/null 2>&1 || true

echo ">>> preparing ${BASE} from ${STAGE3}"
${DOCKER} pull -q "${STAGE3}" >/dev/null

# Not --rm: the whole point is to commit this container afterwards.
# -i or the heredoc below never reaches bash and the container exits silently.
${DOCKER} run -i --privileged --name "${container}" \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${SIGNING_GNUPGHOME}:/root/.gnupg" \
    -e "MAKEOPTS=${MAKEOPTS}" -e "JOBS=${JOBS}" -e "SIGNING_KEY=${SIGNING_KEY}" \
    "${STAGE3}" /bin/bash -euo pipefail -s <<'INNER'

# The signing command is flock /run/lock/portage-binpkg-gpg.lock ...; stage3
# has no /run/lock, so flock fails and portage reports the unlock as failed.
mkdir -p /run/lock /etc/portage/repos.conf

cat > /etc/portage/repos.conf/gentoo-zh.conf <<EOF
[gentoo-zh]
location = /var/db/repos/gentoo-zh
auto-sync = no
EOF

# The official binhost builds amd64 with -march=x86-64 -mtune=generic. Portage
# does not compare CFLAGS when accepting a binary package, so this is the one
# setting standing between a user on an older CPU and an illegal instruction.
cat >> /etc/portage/make.conf <<EOF

CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"
CXXFLAGS="\${CFLAGS}"
MAKEOPTS="${MAKEOPTS}"

ACCEPT_KEYWORDS="~amd64"
ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"

# 签名配置不写在这里。写进基础镜像会让这个镜像只有持有密钥的人能用，
# 而它对 autobump 的试构建、overlay 的 CI 同样有价值。签名是发布环节的事，
# 由 build-container.sh 在构建时追加。
FEATURES="buildpkg getbinpkg binpkg-multi-instance parallel-fetch -news"

EMERGE_DEFAULT_OPTS="--jobs=${JOBS} --load-average=$(nproc) --quiet-build"
EOF

# Gentoo's release keys, for verify-signature against the official binhost.
getuto

# Signing uses /root/.gnupg, verification uses /etc/portage/gnupg. Without our
# public key in the latter, portage refuses the packages it just signed itself.
# --quick-lsign-key wants a tty even with --batch --yes, hence ownertrust.
gpg --homedir /root/.gnupg --armor --export "${SIGNING_KEY}" > /tmp/binhost.asc
gpg --homedir /etc/portage/gnupg --batch --import /tmp/binhost.asc
echo "${SIGNING_KEY}:6:" | gpg --homedir /etc/portage/gnupg --batch --import-ownertrust

# 导入之后必须重算 trustdb 并让它可读，getuto 对自己的密钥做的就是这两步。
# 验签以 portage 用户执行，该用户对 trustdb 没有写入权限；算不出信任链时即使 GOODSIG
# 也只报 [unknown]，portage 照样拒收。
gpg --homedir /etc/portage/gnupg --batch --check-trustdb
chmod ugo+r /etc/portage/gnupg/trustdb.gpg

echo ">>> aligning @world with the tree"
# --keep-going 会跳过装不上的包继续走，所以退出码非零不代表整轮无效，但也不能
# 当没事：对齐没做完的根编出来的包会链到旧库上。记一个标记，宿主那边据此决定
# 要不要 commit。
if ! emerge --update --deep --newuse --usepkg --keep-going --quiet-build @world; then
    echo "!!! @world 未能完全对齐"
    touch /tmp/world-incomplete
fi

# perl 大版本一升，装在旧 vendor_perl/<旧版本>/<arch>/ 里的 XS 模块就落在
# @INC 之外，包还在、模块却载入不了。configure 检测得到 intltool-update 却
# 找不到 XML::Parser，报的错和缺依赖一模一样。实测 5.42 升 5.44 后
# app-i18n/libkkc 就是这样挂的，perl-cleaner 之后 XML::Parser 立刻能载入。
echo ">>> perl-cleaner"
perl-cleaner --all -- --quiet-build || echo "!!! perl-cleaner 未跑完"

# Drop binary packages for versions the tree no longer has. Without this the
# cache only ever grows, and a stale version could still be published.
eclean-pkg --deep 2>/dev/null || true

# getuto 会生成一把 "Portage Local Trust Key" 并把口令明文写在 pass 里，用来
# 本地签名它导入的 Gentoo 发行密钥。那一步已经做完、结果落在 trustdb.gpg 里，
# 之后验签只读 pubring 和 trustdb，私钥再也用不到（实测删掉后
# gpg --verify 仍然 Good signature [ultimate]）。
#
# 不删除时，PUBLISH=1 推到 ghcr 的镜像会带着一把私钥和它的明文口令。
rm -rf /etc/portage/gnupg/private-keys-v1.d \
       /etc/portage/gnupg/pass \
       /etc/portage/gnupg/openpgp-revocs.d
INNER

# commit 之前记下上上代的 ID：下面会把当前这代 tag 成 -prev，
# 再上一代就没有名字了。
previous=$(${DOCKER} image inspect "${BASE}-prev" --format '{{.Id}}' 2>/dev/null || true)

# @world 没对齐就不要盖掉现有的镜像：宁可继续用上一代（顶多旧一点），
# 也不要拿一个链到旧库的根去编 186 个包。
# 容器此时已经停止，只能 cp 不能 exec
if ${DOCKER} cp "${container}:/tmp/world-incomplete" - >/dev/null 2>&1; then
    ${DOCKER} rm -f "${container}" >/dev/null
    die "@world 未能对齐，保留原有的 ${BASE} 不动"
fi

echo ">>> committing ${BASE}"
# 上一代保留成 -prev：新镜像万一有问题，不用再花一个多小时重建。
if ${DOCKER} image inspect "${BASE}" >/dev/null 2>&1; then
    ${DOCKER} tag "${BASE}" "${BASE}-prev"
fi
${DOCKER} commit "${container}" "${BASE}" >/dev/null
${DOCKER} rm -f "${container}" >/dev/null

# 再上一代（被 -prev 顶掉的那个）成了悬空镜像。每周刷新一次、一次约 4 GB，
# 不清理会堆着。按 ID 删这一个，不用 image prune——那会连这台机器上别人的
# 悬空镜像一起清掉。
if [[ -n ${previous} ]]; then
    current=$(${DOCKER} image inspect "${BASE}" --format '{{.Id}}')
    if [[ ${previous} != "${current}" ]]; then
        ${DOCKER} rmi "${previous}" >/dev/null 2>&1 || true
    fi
fi

echo ">>> ${BASE} ready"

# --- optional publish ---------------------------------------------------------
# Worth doing for two reasons: it is a backup of an environment that costs an
# hour to rebuild, and it lets anyone see exactly what the packages were built
# in.
#
# 可以公开：docker commit 不收录挂载点，签名密钥在 /root/.gnupg，不在镜像里。
# getuto 生成的本地信任密钥在上面已经删掉。镜像里剩下的是对齐好的 @world、
# 验签用的公钥环和指纹，本来就是公开的。都是查过的，不是假设的。

if [[ -n ${PUBLISH:-} ]]; then
    remote="${REGISTRY:-ghcr.io/gentoo-zh}/binhost-base:${TAG}"
    echo ">>> pushing ${remote}"
    ${DOCKER} tag "${BASE}" "${remote}"
    ${DOCKER} push "${remote}"
fi
