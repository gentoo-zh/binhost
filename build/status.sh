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
# How long the index may sit still before something is wrong. The build runs
# nightly (binhost-build.timer), so the threshold is two rounds. A failed round
# alerts through cycle.sh; this one covers the build machine not running at all
# -- timer disabled, machine off, systemd not coming up. The heartbeat check
# covers only the mirror, and the build machine has no other liveness signal,
# so the index's freshness is it.
#
# This was 14 days, from when the full build was triggered by hand. The number
# did not follow the timer, which meant a stopped build went unnoticed for two
# weeks.
INDEX_MAX_AGE_D="${INDEX_MAX_AGE_D:-2}"
# The distfiles sync runs hourly; six hours is late enough to mean something is
# wrong rather than one slow round.
DIST_MAX_AGE_H="${DIST_MAX_AGE_H:-6}"
# The two expiries are different in kind. Rotating the signing key needs an
# overlap so users who have not picked up the new public key do not suddenly
# fail verification, hence half a year of warning. The TLS certificate renews
# itself and Let's Encrypt only signs 90 days, so the threshold has to sit below
# the renewal cycle or it alerts every day.
KEY_WARN_DAYS="${KEY_WARN_DAYS:-180}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"
EXPORTER_PORT="${EXPORTER_PORT:-9100}"
# 磁盘。distfiles 只涨不缩，回收桶还要再留十四天的量。盘满时 emirrordist 写出
# 的是截断的文件，而它照样退出 0——没有任何一处会说出来。
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
DISK_PATH="${DISK_PATH:-/srv/pub}"

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

# --- 磁盘 ---------------------------------------------------------------------
# 只在这台上查：另一份 status.sh 跑在别处，那边没有 /srv/pub。
if [[ -d ${DISK_PATH} ]]; then
    read -r used avail pct < <(df -P "${DISK_PATH}" | awk 'NR==2 {gsub(/%/,"",$5); print $3, $4, $5}')
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
        # Arithmetic expansion turns an empty or non-numeric value into 0
        # without a word, which makes age come out as fifty-odd years. Without
        # this test nobody would ever find out.
        bad "index" "TIMESTAMP 读不出来"
    else
        age=$(( ( $(date +%s) - ts ) / 86400 ))
        if (( age >= INDEX_MAX_AGE_D )); then
            bad "index" "${age}d 未更新（超过 ${INDEX_MAX_AGE_D}d）"
        elif [[ ! ${n} =~ ^[0-9]+$ ]] || (( n == 0 )); then
            # 一份 PACKAGES: 0 而时间戳新鲜的索引，原来这里是绿的，下面取包
            # 那段又因为拿不到 PATH 整个跳过，退出码 0。distfiles 那边有对应
            # 的一条，索引这边缺了。
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
        # 没有 else 时这一整项静默消失，而它正是用来发现索引与文件对不上的。
        bad "package fetch" "索引里取不到一条 PATH"
    fi
fi

# --- distfiles ----------------------------------------------------------------
# The hourly sync is the only thing that keeps distfiles current, and until now
# nothing outside it looked at the result: with the cron entry gone or the
# machine wedged, neither host would have noticed. distfiles-status.json is
# written at the end of each sync, so its age answers whether the sync still
# runs.
dist=$(curl -fsS --max-time 15 "${SITE}/distfiles-status.json" 2>/dev/null)
if [[ -z ${dist} ]]; then
    bad "distfiles" "取不到 distfiles-status.json"
else
    dts=$(grep -o '"generated":[0-9]*' <<< "${dist}" | cut -d: -f2)
    dn=$(grep -o '"files":[0-9]*' <<< "${dist}" | cut -d: -f2)
    if [[ ! ${dts} =~ ^[0-9]+$ || ! ${dn} =~ ^[0-9]+$ ]]; then
        bad "distfiles" "status 读不出来"
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
# The node once dropped off Grafana and nothing here said so. /etc/nftables.conf
# had been reapplied from a copy that predated the port 9100 rule, scrapes were
# refused from then on, and every other check stayed green. Grafana showed it;
# nobody was watching Grafana.
#
# Scraping comes from another machine, so this cannot test it end to end. It
# tests the two things that were wrong: the exporter answers, and the firewall
# names somewhere for it to answer to.
#
# The firewall half applies only where the firewall is ours. deploy/nftables.conf
# is the mirror's; the build machine runs iptables that came with it, and asking
# nft about a table that is not there returns nothing -- which reads exactly like
# a missing rule. That cost a false alarm on a healthy host.
if ! command -v node_exporter >/dev/null 2>&1; then
    note "node_exporter" "not on this host"
elif ! curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:${EXPORTER_PORT}/metrics"; then
    bad "node_exporter" "本机 ${EXPORTER_PORT} 没有回应"
else
    # Read the chain once and match against the text. Piping it into grep -q
    # races: grep exits on the first match, nft dies of SIGPIPE, and pipefail
    # reports the pipeline as failed. Measured at one run in ten here, which for
    # a nightly check is a false alarm every couple of weeks.
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
            if (( monitors == 0 )); then
                # The set is emptied by nftables.conf's flush ruleset, and
                # install.sh refills it from MONITORS. Install without MONITORS
                # and the port is open to nobody -- the rule is there and
                # nothing gets through.
                bad "node_exporter" "monitor_hosts 是空的，没有抓取源连得上"
            else
                note "node_exporter" "ok，放行 ${monitors} 个抓取源"
            fi
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

# 有问题却没有告警配置时要说出来。这台的 cron mail 没有出口，只印在 stdout
# 等于没人知道，而「没配告警」和「一切正常」在外面看起来一模一样。
if (( problems > 0 )) && [[ ! -r ${ALERT_CONF} ]]; then
    echo "!! 有 ${problems} 项未通过，但 ${ALERT_CONF} 读不到，告警发不出去" >&2
fi

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
