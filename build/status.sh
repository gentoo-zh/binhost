#!/bin/bash

set -uo pipefail

SITE="${SITE:-https://distfiles.gentoozh.org}"
TAG="${TAG:-x86-64}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"
HEARTBEAT="${HEARTBEAT:-/srv/mirrors/.health}"
HEARTBEAT_MAX_H="${HEARTBEAT_MAX_H:-26}"
INDEX_MAX_AGE_D="${INDEX_MAX_AGE_D:-2}"
DIST_MAX_AGE_H="${DIST_MAX_AGE_H:-6}"
KEY_WARN_DAYS="${KEY_WARN_DAYS:-180}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"
EXPORTER_PORT="${EXPORTER_PORT:-9100}"
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
DISK_PATH="${DISK_PATH:-/srv/pub}"
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

if [[ ! -d ${SITE_WORK}/.git && -d ${SITE_DEST} && -e ${SITE_DEST}/index.html ]]; then
    bad "站点同步" "${SITE_WORK} 不是仓库副本，而 ${SITE_DEST} 里有站点内容"
elif [[ -d ${SITE_WORK}/.git ]]; then
    fetched=$(stat -c %Y "${SITE_WORK}/.git/FETCH_HEAD" 2>/dev/null || echo 0)
    age_h=$(( ($(date +%s) - fetched) / 3600 ))
    here_site=$(git -C "${SITE_WORK}" rev-parse HEAD 2>/dev/null)
    marked=$(cat "${SITE_WORK}/.synced" 2>/dev/null || true)
    drift=$(diff -rq "${SITE_WORK}/site/assets" "${SITE_DEST}/assets" 2>&1 | wc -l)
    pages=0
    for f in "${SITE_WORK}"/site/*.html; do
        cmp -s "${f}" "${SITE_DEST}/$(basename "${f}")" || pages=$((pages + 1))
    done
    if (( fetched == 0 )); then
        bad "站点同步" "${SITE_WORK}/.git/FETCH_HEAD 不存在，同步从未执行"
    elif (( age_h >= SITE_STALE_H )); then
        bad "站点同步" "上次拉取在 ${age_h} 小时前，五分钟一次的同步已停止"
    elif [[ ${marked} != "${here_site}" ]]; then
        bad "站点同步" "仓库副本在 ${here_site:0:8}，上次完成的是 ${marked:0:8}，最近一轮未完成"
    elif (( drift )); then
        bad "站点同步" "assets 有 ${drift} 处与仓库副本不一致，rsync 未完成"
    elif (( pages )); then
        bad "站点同步" "${pages} 个页面与仓库副本不一致，rsync 未完成"
    elif [[ ! -r ${SITE_DEST}/gentoo-zh-binhost.asc ]]; then
        bad "站点同步" "发布目录里没有公钥，用户按站点第 1 步无法获取它"
    elif ! cmp -s "${SITE_WORK}/site/gentoo-zh-binhost.asc" "${SITE_DEST}/gentoo-zh-binhost.asc"; then
        bad "站点同步" "仓库里的公钥与已发布的不一致，指纹守卫可能拦下了它"
    else
        note "站点同步" "${here_site:0:8}，${age_h} 小时内已拉取"
    fi
fi

if [[ -d ${SIGNING_GNUPGHOME} ]]; then
    if [[ -z ${SIGNING_KEY:-} ]]; then
        SIGNING_KEY=$(sed -n 's/^Environment=SIGNING_KEY=//p' \
            /etc/systemd/system/binhost-build.service 2>/dev/null | tail -1)
    fi
    if [[ -z ${SIGNING_KEY:-} ]]; then
        bad "signing key" "无法确定应使用的密钥指纹，SIGNING_KEY 未设置"
    else
        secret=$(sudo gpg --homedir "${SIGNING_GNUPGHOME}" --with-colons \
                 --list-secret-keys "${SIGNING_KEY}" 2>/dev/null)
        gpg_rc=$?
        caps=$(awk -F: '/^sec:/{print $12; exit}' <<< "${secret}")
        trust=$(awk -F: '/^sec:/{print $2; exit}' <<< "${secret}")
        expiry=$(awk -F: '/^sec:/{print $7; exit}' <<< "${secret}")
        if (( gpg_rc != 0 )) || ! grep -q '^sec:' <<< "${secret}"; then
            bad "signing key" "${SIGNING_GNUPGHOME} 里没有 ${SIGNING_KEY:0:8} 的私钥"
        elif [[ ${trust} == r ]]; then
            bad "signing key" "${SIGNING_KEY:0:8} 已撤销"
        elif [[ ${caps} != *s* ]]; then
            bad "signing key" "${SIGNING_KEY:0:8} 没有签名能力（capabilities=${caps:-无}）"
        elif [[ -n ${expiry} && ${expiry} != 0 ]]; then
            left=$(( (expiry - $(date +%s)) / 86400 ))
            if (( left < KEY_WARN_DAYS )); then
                bad "signing key" "${SIGNING_KEY:0:8} 将在 ${left} 天后过期"
            else
                note "signing key" "${SIGNING_KEY:0:8}，${left} 天后过期"
            fi
        else
            note "signing key" "${SIGNING_KEY:0:8}，无过期时间"
        fi
    fi
else
    note "signing key" "本机没有该目录"
fi

if [[ -d ${DISK_PATH} ]]; then
    read -r avail pct < <(df -P "${DISK_PATH}" | awk 'NR==2 {gsub(/%/,"",$5); print $4, $5}')
    human() { awk -v k="$1" 'BEGIN { split("K M G T", u); i=1; while (k>=1024 && i<4) { k/=1024; i++ } printf "%.0f%s", k, u[i] }'; }
    if (( pct >= DISK_WARN_PCT )); then
        bad "磁盘" "${DISK_PATH} 用了 ${pct}%，剩 $(human "${avail}")"
    else
        note "磁盘" "${pct}%，剩 $(human "${avail}")"
    fi
fi

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

head=$(curl -fsS --max-time 15 -r 0-2047 "${SITE}/binpkgs/${TAG}/Packages" 2>/dev/null)
if [[ -z ${head} ]]; then
    bad "index" "not published"
else
    ts=$(grep -m1 '^TIMESTAMP: ' <<< "${head}" | awk '{print $2}')
    n=$(grep -m1 '^PACKAGES: ' <<< "${head}" | awk '{print $2}')
    if [[ ! ${ts} =~ ^[0-9]+$ ]]; then
        bad "index" "TIMESTAMP 无法解析"
    else
        age=$(( ( $(date +%s) - ts ) / 86400 ))
        if (( age >= INDEX_MAX_AGE_D )); then
            bad "index" "${age}d 未更新（超过 ${INDEX_MAX_AGE_D}d）"
        elif [[ ! ${n} =~ ^[0-9]+$ ]] || (( n == 0 )); then
            bad "index" "索引里一个包都没有"
        else
            note "index" "${n} packages, ${age}d old"
        fi
    fi
fi

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
        bad "package fetch" "索引里无法获取一条 PATH"
    fi
fi

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

if ! command -v node_exporter >/dev/null 2>&1; then
    note "node_exporter" "not on this host"
elif ! curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:${EXPORTER_PORT}/metrics"; then
    bad "node_exporter" "本机 ${EXPORTER_PORT} 没有回应"
else
    rules=$(sudo -n nft list chain inet filter input 2>/dev/null)
    if [[ -z ${rules} ]]; then
        note "node_exporter" "应答正常（防火墙不由这里管）"
    elif [[ ${rules} != *"dport ${EXPORTER_PORT}"* ]]; then
        bad "node_exporter" "防火墙没有放行 ${EXPORTER_PORT} 的规则"
    else
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


if (( problems > 0 )) && [[ ! -r ${ALERT_CONF} ]]; then
    echo "!! 有 ${problems} 项未通过，但 ${ALERT_CONF} 读不到，告警传送失败" >&2
fi

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
