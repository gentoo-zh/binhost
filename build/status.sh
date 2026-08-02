#!/bin/bash
# Health check for the things that fail silently.
#
# All three of these break users without anyone noticing: an expired signing
# key makes verify-signature reject everything, an expired certificate breaks
# the index fetch, and a stale index means new packages are never seen.

set -uo pipefail

SITE="${SITE:-https://distfiles.gentoozh.org}"
TAG="${TAG:-x86-64}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"
HEARTBEAT="${HEARTBEAT:-/srv/mirrors/.health}"
HEARTBEAT_MAX_H="${HEARTBEAT_MAX_H:-26}"
# Two rounds of binhost-build.timer. A failed round alerts through cycle.sh, so
# what this covers is the build machine not running at all, and the index's age
# is the only liveness signal that machine has -- the heartbeat is the mirror's.
INDEX_MAX_AGE_D="${INDEX_MAX_AGE_D:-2}"
# The distfiles sync runs hourly; six hours is late enough to mean something is
# wrong rather than one slow round.
DIST_MAX_AGE_H="${DIST_MAX_AGE_H:-6}"
# Rotating the signing key needs an overlap, or users who have not picked up the
# new public key start failing verification, hence half a year of warning. The
# certificate renews itself on a 90-day cycle, so its threshold has to sit below
# that or it alerts every day.
KEY_WARN_DAYS="${KEY_WARN_DAYS:-180}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"
EXPORTER_PORT="${EXPORTER_PORT:-9100}"
# 磁盘。distfiles 只涨不缩，回收桶还要再留十四天的量。盘满时 emirrordist 写出
# 的是截断的文件，而它照样退出 0——没有任何一处会说出来。
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
DISK_PATH="${DISK_PATH:-/srv/pub}"
# 部署的那一份是哪个提交。install.sh 与 install-builder.sh 各写一份，两台机器
# 上的路径不同，谁在就查谁。
VERSION_FILE="${VERSION_FILE:-}"
REPO_API="${REPO_API:-https://api.github.com/repos/gentoo-zh/binhost/commits/master}"
MONITORS_FILE="${MONITORS_FILE:-/usr/local/lib/binhost/MONITORS}"
SITE_WORK="${SITE_WORK:-/var/lib/binhost-site}"
SITE_STALE_H="${SITE_STALE_H:-2}"
SITE_DEST="${SITE_DEST:-/srv/mirrors}"

problems=0
failures=()
note() { printf '  %-22s %s\n' "$1" "$2"; }
bad()  {
    problems=$((problems + 1))
    failures+=("$1: $2")
    printf '  %-22s %s  <-- \n' "$1" "$2"
}

days_until() { echo $(( ( $(date -d "$1" +%s) - $(date +%s) ) / 86400 )); }

# --- 部署版本 ------------------------------------------------------------------
# 两台机器上的脚本都是 rsync 过去的拷贝，没有任何一处会说它落后了。只报告，
# 不自动更新：部署要避开建置中的那一轮，那是 install-builder.sh 的事。
if [[ -z ${VERSION_FILE} ]]; then
    for f in /usr/local/lib/binhost/VERSION /var/lib/binhost/build/VERSION; do
        [[ -r ${f} ]] && { VERSION_FILE="${f}"; break; }
    done
fi
if [[ -n ${VERSION_FILE} && -r ${VERSION_FILE} ]]; then
    here=$(tr -d ' \n' < "${VERSION_FILE}")
    there=$(curl -fsS --max-time 20 "${REPO_API}" 2>/dev/null |
            sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)",$/\1/p' | head -1)
    if [[ -z ${there} ]]; then
        note "部署版本" "${here:0:8}，远端不可达，未比对"
    elif [[ ${here} == "${there}" ]]; then
        note "部署版本" "${here:0:8}，与 master 一致"
    else
        bad "部署版本" "已部署 ${here:0:8}，master 为 ${there:0:8}，该机运行的不是当前代码"
    fi
else
    bad "部署版本" "缺少 VERSION，安装时未记录提交号"
fi

# --- 站点同步 ------------------------------------------------------------------
if [[ ! -d ${SITE_WORK}/.git && -d ${SITE_DEST} && -e ${SITE_DEST}/index.html ]]; then
    bad "站点同步" "${SITE_WORK} 不是仓库副本，而 ${SITE_DEST} 里有站点内容"
elif [[ -d ${SITE_WORK}/.git ]]; then
    fetched=$(stat -c %Y "${SITE_WORK}/.git/FETCH_HEAD" 2>/dev/null || echo 0)
    age_h=$(( ($(date +%s) - fetched) / 3600 ))
    here_site=$(git -C "${SITE_WORK}" rev-parse HEAD 2>/dev/null)
    served=$(md5sum "${SITE_DEST}/index.html" 2>/dev/null | cut -d' ' -f1)
    onbox=$(md5sum "${SITE_WORK}/site/index.html" 2>/dev/null | cut -d' ' -f1)
    if (( fetched == 0 )); then
        bad "站点同步" "${SITE_WORK}/.git/FETCH_HEAD 不存在，同步从未执行"
    elif (( age_h >= SITE_STALE_H )); then
        bad "站点同步" "上次拉取在 ${age_h} 小时前，五分钟一次的同步已停止"
    elif [[ -z ${served} || -z ${onbox} ]]; then
        bad "站点同步" "index.html 在仓库副本或发布目录里读不到，无法比对"
    elif [[ ${served} != "${onbox}" ]]; then
        bad "站点同步" "仓库副本与发布目录不一致，rsync 未完成"
    elif [[ -r ${SITE_WORK}/site/gentoo-zh-binhost.asc && -r ${SITE_DEST}/gentoo-zh-binhost.asc ]] &&
         ! cmp -s "${SITE_WORK}/site/gentoo-zh-binhost.asc" "${SITE_DEST}/gentoo-zh-binhost.asc"; then
        # 指纹守卫拒绝同步公钥时只往 stderr 写一行，而那一行没有人读得到
        bad "站点同步" "仓库里的公钥与已发布的不一致，指纹守卫可能拦下了它"
    else
        note "站点同步" "${here_site:0:8}，${age_h} 小时内已拉取"
    fi
fi

# --- signing key --------------------------------------------------------------
if [[ -d ${SIGNING_GNUPGHOME} ]]; then
    keys=$(sudo gpg --homedir "${SIGNING_GNUPGHOME}" --list-keys --with-colons 2>/dev/null)
    gpg_rc=$?
    expiry=$(awk -F: '/^pub/{print $7; exit}' <<< "${keys}")
    # 空钥匙圈返回 0，输出里只有一条 tru: 记录，所以要看有没有 pub:
    if (( gpg_rc != 0 )) || ! grep -q '^pub:' <<< "${keys}"; then
        bad "signing key" "读不到 ${SIGNING_GNUPGHOME} 里的公钥"
    elif [[ -n ${expiry} && ${expiry} != 0 ]]; then
        left=$(( (expiry - $(date +%s)) / 86400 ))
        if (( left < KEY_WARN_DAYS )); then
            bad "signing key" "expires in ${left}d"
        else
            note "signing key" "expires in ${left}d"
        fi
    else
        note "signing key" "no expiry"
    fi
else
    note "signing key" "not on this host"
fi

# --- 磁盘 ---------------------------------------------------------------------
# 只在这台上查：另一份 status.sh 跑在别处，那边没有 /srv/pub。
if [[ -d ${DISK_PATH} ]]; then
    read -r avail pct < <(df -P "${DISK_PATH}" | awk 'NR==2 {gsub(/%/,"",$5); print $4, $5}')
    human() { awk -v k="$1" 'BEGIN { split("K M G T", u); i=1; while (k>=1024 && i<4) { k/=1024; i++ } printf "%.0f%s", k, u[i] }'; }
    if (( pct >= DISK_WARN_PCT )); then
        bad "磁盘" "${DISK_PATH} 用了 ${pct}%，剩 $(human "${avail}")"
    else
        note "磁盘" "${pct}%，剩 $(human "${avail}")"
    fi
fi

# --- TLS ----------------------------------------------------------------------
host="${SITE#https://}"
expiry=$(echo | openssl s_client -connect "${host}:443" -servername "${host}" 2>/dev/null |
         openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [[ -n ${expiry} ]]; then
    left=$(days_until "${expiry}")
    if (( left < CERT_WARN_DAYS )); then
        bad "TLS certificate" "expires in ${left}d"
    else
        note "TLS certificate" "expires in ${left}d"
    fi
else
    bad "TLS certificate" "could not read"
fi

# --- index --------------------------------------------------------------------
head=$(curl -fsS --max-time 15 -r 0-2047 "${SITE}/binpkgs/${TAG}/Packages" 2>/dev/null)
if [[ -z ${head} ]]; then
    bad "index" "not published"
else
    ts=$(grep -m1 '^TIMESTAMP: ' <<< "${head}" | awk '{print $2}')
    n=$(grep -m1 '^PACKAGES: ' <<< "${head}" | awk '{print $2}')
    if [[ ! ${ts} =~ ^[0-9]+$ ]]; then
        # 算术展开把空值当成 0，age 会算成五十多年，而且一声不吭
        bad "index" "TIMESTAMP 无法解析"
    else
        age=$(( ( $(date +%s) - ts ) / 86400 ))
        if (( age >= INDEX_MAX_AGE_D )); then
            bad "index" "${age}d 未更新（超过 ${INDEX_MAX_AGE_D}d）"
        elif [[ ! ${n} =~ ^[0-9]+$ ]] || (( n == 0 )); then
            # PACKAGES: 0 而时间戳新鲜时，只查时间戳这一项仍是绿的
            bad "index" "索引里一个包都没有"
        else
            note "index" "${n} packages, ${age}d old"
        fi
    fi
fi

# --- a package actually resolves ----------------------------------------------
# Fetch one package the index claims to have. Publishing is two steps -- files
# first, then the index -- and an interruption between them leaves the two
# disagreeing, which reading the index alone cannot show.
if [[ -n ${head:-} ]]; then
    path=$(curl -fsS --max-time 20 "${SITE}/binpkgs/${TAG}/Packages" 2>/dev/null |
           awk '/^PATH: /{print $2; exit}')
    if [[ -n ${path} ]]; then
        code=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -L \
               "${SITE}/binpkgs/${TAG}/${path}" 2>/dev/null)
        if [[ ${code} == 200 ]]; then
            note "package fetch" "ok"
        else
            bad "package fetch" "HTTP ${code}"
        fi
    else
        # 没有 else 时这一整项静默消失，而它正是用来发现索引与文件不一致的。
        bad "package fetch" "索引里无法获取一条 PATH"
    fi
fi

# --- distfiles ----------------------------------------------------------------
# distfiles-status.json is written at the end of each hourly sync, so its age
# answers whether that sync still runs. Nothing else looks at the result.
dist=$(curl -fsS --max-time 15 "${SITE}/distfiles-status.json" 2>/dev/null)
if [[ -z ${dist} ]]; then
    bad "distfiles" "无法获取 distfiles-status.json"
else
    dts=$(grep -o '"generated":[0-9]*' <<< "${dist}" | cut -d: -f2)
    dn=$(grep -o '"files":[0-9]*' <<< "${dist}" | cut -d: -f2)
    if [[ ! ${dts} =~ ^[0-9]+$ || ! ${dn} =~ ^[0-9]+$ ]]; then
        bad "distfiles" "status 无法解析"
    elif (( dn == 0 )); then
        bad "distfiles" "一个文件都没有"
    else
        dage=$(( ( $(date +%s) - dts ) / 3600 ))
        if (( dage >= DIST_MAX_AGE_H )); then
            bad "distfiles" "${dage}h 未同步（超过 ${DIST_MAX_AGE_H}h）"
        else
            note "distfiles" "${dn} files, ${dage}h old"
        fi
    fi
fi

# --- node_exporter --------------------------------------------------------------
# Scraping comes from another machine, so this cannot be tested end to end. It
# tests the two halves that live here: the exporter answers, and the firewall
# names somewhere for it to answer to.
#
# The firewall half only where the firewall is ours. deploy/nftables.conf is the
# mirror's; the build machine runs the iptables it came with, and asking nft
# about a table that is not there returns nothing -- indistinguishable from a
# missing rule, and it cost a false alarm on a healthy host.
if ! command -v node_exporter >/dev/null 2>&1; then
    note "node_exporter" "not on this host"
elif ! curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:${EXPORTER_PORT}/metrics"; then
    bad "node_exporter" "本机 ${EXPORTER_PORT} 没有回应"
else
    # 读一次再匹配文本。接 grep -q 会有竞争：grep 命中即退出，nft 收到
    # SIGPIPE，pipefail 把整条管线算作失败。实测每十次约一次。
    rules=$(sudo -n nft list chain inet filter input 2>/dev/null)
    if [[ -z ${rules} ]]; then
        note "node_exporter" "应答正常（防火墙不由这里管）"
    elif [[ ${rules} != *"dport ${EXPORTER_PORT}"* ]]; then
        bad "node_exporter" "防火墙没有放行 ${EXPORTER_PORT} 的规则"
    else
        # 读得到和读不到要分开。nft 失败、集合改名、sudo 被拒都会得到 0，
        # 和「集合真的是空的」看起来一样。
        if ! set_out=$(sudo -n nft list set inet filter monitor_hosts 2>/dev/null); then
            bad "node_exporter" "读不到 monitor_hosts 集合"
        else
            monitors=$(grep -Eo '[0-9]+(\.[0-9]+){3}' <<< "${set_out}" | wc -l)
            want=0
            [[ -r ${MONITORS_FILE} ]] &&
                want=$(grep -Eo '[0-9]+(\.[0-9]+){3}' "${MONITORS_FILE}" | wc -l)
            if (( monitors > 0 )); then
                note "node_exporter" "ok，放行 ${monitors} 个抓取源"
            elif (( want > 0 )); then
                bad "node_exporter" "安装时配置了 ${want} 个抓取源，当前集合为空"
            else
                note "node_exporter" "未配置抓取源，${EXPORTER_PORT} 不对外开放"
            fi
        fi
    fi
fi

# --- heartbeat ----------------------------------------------------------------
# Alerting only on failure makes silence ambiguous: a dead machine looks like a
# healthy one. Each run stamps a file the web server exposes, and a copy of this
# script elsewhere checks the stamp's age. The mirror writes the stamp before it
# reads it, so it never reports itself stale; the off-box copy is what notices.

if [[ -w $(dirname "${HEARTBEAT}") ]] 2>/dev/null; then
    date +%s > "${HEARTBEAT}"
fi

stamp=$(curl -fsS --max-time 15 "${SITE}/.health" 2>/dev/null | tr -dc '0-9')
if [[ -z ${stamp} ]]; then
    bad "heartbeat" "无法获取 ${SITE}/.health"
else
    age_h=$(( ( $(date +%s) - stamp ) / 3600 ))
    if (( age_h >= HEARTBEAT_MAX_H )); then
        bad "heartbeat" "${age_h}h 未更新（阈值 ${HEARTBEAT_MAX_H}h）"
    else
        note "heartbeat" "${age_h}h 前"
    fi
fi

# --- alert --------------------------------------------------------------------
# 这台的 cron mail 没有出口：nullmailer 装了但没配 relay，失败只会躺在本机的
# 信箱里。所以发 Telegram。

# 「没配告警」和「一切正常」在外面看起来一样，要说出来。
if (( problems > 0 )) && [[ ! -r ${ALERT_CONF} ]]; then
    echo "!! 有 ${problems} 项未通过，但 ${ALERT_CONF} 读不到，告警传送失败" >&2
fi

# 只有定时执行才发群通知。手动查看状态时每次都发，一晚上二十余条。
if (( problems > 0 )) && [[ ${BINHOST_ALERT:-} == 1 ]] && [[ -r ${ALERT_CONF} ]]; then
    # shellcheck source=/dev/null
    . "${ALERT_CONF}"
    if [[ -z ${TELEGRAM_TOKEN:-} || -z ${TELEGRAM_CHAT:-} ]]; then
        echo "!!! ${ALERT_CONF} 缺 TELEGRAM_TOKEN 或 TELEGRAM_CHAT，本次告警未发出" >&2
    fi
    if [[ -n ${TELEGRAM_TOKEN:-} && -n ${TELEGRAM_CHAT:-} ]]; then
        text="binhost 检查未通过（$(hostname)）:"
        for f in "${failures[@]}"; do
            text+=$'\n'"• ${f}"
        done
        curl -fsS --max-time 20 -o /dev/null \
            "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
            --data-urlencode "text=${text}" \
            --data "disable_notification=false" || echo "!!! 告警发送失败" >&2
    fi
fi

exit $(( problems > 0 ))
