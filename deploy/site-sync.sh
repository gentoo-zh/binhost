#!/bin/bash
# Pull the published site onto the mirror. Runs from cron on the mirror itself.
#
# The mirror pulls rather than CI pushing, so nothing outside ever holds a key
# that reaches this machine and there is no inbound path to abuse. The cost is
# that a change lands within the poll interval instead of instantly, which for
# a static site is not a cost worth paying anything for.
#
# Only site content is synced. The nginx configuration stays a manual, root
# operation: a repository push should not be able to change how the server
# behaves.

set -euo pipefail

REPO="${REPO:-https://github.com/gentoo-zh/binhost}"
WORK="${WORK:-/var/lib/binhost-site}"
DEST="${DEST:-/srv/mirrors}"
BRANCH="${BRANCH:-master}"

# A fresh clone has nothing to compare against, so it must always deploy --
# otherwise a newly provisioned mirror waits for the next upstream commit
# before it ever serves the site.
fresh=0
if [[ -d ${WORK}/.git ]]; then
    git -C "${WORK}" fetch --quiet origin "${BRANCH}"
else
    git clone --quiet --depth=1 --branch "${BRANCH}" "${REPO}" "${WORK}"
    fresh=1
fi

before=$(git -C "${WORK}" rev-parse HEAD)
git -C "${WORK}" reset --quiet --hard "origin/${BRANCH}"
after=$(git -C "${WORK}" rev-parse HEAD)

(( fresh )) || [[ ${before} != "${after}" ]] || exit 0

# --delete only inside assets/: everything else in DEST belongs to the package
# publisher, and wiping it would take the repository down with the site.
rsync -a --delete "${WORK}/site/assets/" "${DEST}/assets/"
# packages.json 不在这里：它由镜像机上的 gen-packages.py 按 overlay 生成，
# 内容跟着 overlay 走，不跟着本仓库的提交走。
# 签名公钥是用户导入的信任锚。让它跟着这条五分钟一次的自动通道走，
# 任何能改仓库的人换掉它，镜像机会自动照做，而用户看到的仍然是我们的域名。
# 所以只在指纹与本机记录的一致时才同步——这份指纹写在服务器上，不从仓库读。
FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"
if [[ -r ${FPR_FILE} ]]; then
    want=$(tr -d ' \n' < "${FPR_FILE}")
    got=$(gpg --with-colons --show-keys "${WORK}/site/gentoo-zh-binhost.asc" 2>/dev/null |
          awk -F: '/^fpr:/{print $10; exit}')
    if [[ ${got} == "${want}" ]]; then
        rsync -a "${WORK}/site/gentoo-zh-binhost.asc" "${DEST}/"
    else
        echo "!! 公钥指纹对不上，没有同步：仓库里是 ${got:-空}，本机记录是 ${want}" >&2
    fi
else
    echo "!! ${FPR_FILE} 不存在，公钥未同步" >&2
fi

# 用 --include/--exclude 而不是逐个列文件名：漏掉一个新页面只是它不上线，
# 而列一个已删除的文件会让 rsync 返回 23，在 set -e 下整个同步都不做。
# 不能直接 site/*.html 加 --delete：DEST 下还有发布出去的包和 distfiles。
rsync -a --include='*.html' --exclude='*' "${WORK}/site/" "${DEST}/"

echo "site updated ${before:0:7} -> ${after:0:7}"
