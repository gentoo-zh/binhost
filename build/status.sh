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
# 索引多久没动就算不对劲。构建每晚一轮（binhost-build.timer），门槛取两轮：
# 一轮失败会由 cycle.sh 自己告警，这一条兜的是构建机整个不动了——定时器被停、
# 机器关机、systemd 起不来。心跳那一条只覆盖镜像机，构建机没有别的存活信号，
# 索引的新鲜度就是它。
#
# 原先是 14 天，注释还写着「全量构建目前是人工触发」。定时构建上线之后这个数
# 没跟着改，意味着构建停摆两周才有人知道。
INDEX_MAX_AGE_D="${INDEX_MAX_AGE_D:-2}"
# 两种到期性质不同。签名密钥轮替要新旧重叠一段，让还没同步到新公钥的用户
# 不至于突然验签失败，所以提前半年提醒；TLS 证书是自动续期的，
# Let's Encrypt 只签 90 天，门槛必须低于续期周期，否则天天在告警。
KEY_WARN_DAYS="${KEY_WARN_DAYS:-180}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"

problems=0
failures=()
note() { printf '  %-22s %s\n' "$1" "$2"; }
bad()  {
    problems=$((problems + 1))
    failures+=("$1: $2")
    printf '  %-22s %s  <-- \n' "$1" "$2"
}

days_until() { echo $(( ( $(date -d "$1" +%s) - $(date +%s) ) / 86400 )); }

# --- signing key --------------------------------------------------------------
if [[ -d ${SIGNING_GNUPGHOME} ]]; then
    expiry=$(sudo gpg --homedir "${SIGNING_GNUPGHOME}" --list-keys --with-colons 2>/dev/null |
             awk -F: '/^pub/{print $7; exit}')
    if [[ -n ${expiry} && ${expiry} != 0 ]]; then
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
        # 算术展开碰上空值或非数字会静默当成 0，那样 age 会变成五十多年，
        # 而下面只要不判就永远不会有人发现。
        bad "index" "TIMESTAMP 读不出来"
    else
        age=$(( ( $(date +%s) - ts ) / 86400 ))
        if (( age > INDEX_MAX_AGE_D )); then
            bad "index" "${age}d 未更新（超过 ${INDEX_MAX_AGE_D}d）"
        else
            note "index" "${n} packages, ${age}d old"
        fi
    fi
fi

# --- a package actually resolves ----------------------------------------------
# 索引说有的包，实际取一个回来。发布是分两步做的（先传包体再换索引），
# 中途中断会让索引和包体对不上，只查索引发现不了。
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
    fi
fi

# --- heartbeat ----------------------------------------------------------------
# Alerting only on failure means silence is ambiguous: a dead machine looks
# exactly like a healthy one. So each run stamps a file the web server exposes,
# and a copy of this script running elsewhere checks how old that stamp is.
#
# On the mirror the stamp is written before it is read, so the mirror never
# reports itself stale -- that is the point. The off-box copy is what notices.

if [[ -w $(dirname "${HEARTBEAT}") ]] 2>/dev/null; then
    date +%s > "${HEARTBEAT}"
fi

stamp=$(curl -fsS --max-time 15 "${SITE}/.health" 2>/dev/null | tr -dc '0-9')
if [[ -z ${stamp} ]]; then
    bad "heartbeat" "取不到 ${SITE}/.health"
else
    age_h=$(( ( $(date +%s) - stamp ) / 3600 ))
    if (( age_h >= HEARTBEAT_MAX_H )); then
        bad "heartbeat" "${age_h}h 未更新（阈值 ${HEARTBEAT_MAX_H}h）"
    else
        note "heartbeat" "${age_h}h 前"
    fi
fi

# --- alert --------------------------------------------------------------------
# Cron mail on this host goes nowhere: nullmailer is installed but has no relay
# configured, so a failure would sit in a local mailbox unread. Post to Telegram
# instead.
#
# Only fires on failure, which means silence is ambiguous -- a dead machine
# looks the same as a healthy one. A dead man's switch would close that gap.

if (( problems > 0 )) && [[ -r ${ALERT_CONF} ]]; then
    # shellcheck source=/dev/null
    . "${ALERT_CONF}"
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
