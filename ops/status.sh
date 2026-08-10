#!/bin/bash

set -uo pipefail

EXIT_ALERTED=10
EXIT_SUPPRESSED=11

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
SITE_LOCK="${SITE_LOCK:-${SITE_WORK}.lock}"
SITE_STALE_H="${SITE_STALE_H:-2}"
SITE_DEST="${SITE_DEST:-/srv/mirrors}"
BUILD_STALE_H="${BUILD_STALE_H:-3}"
INDEX_SAMPLE_COUNT="${INDEX_SAMPLE_COUNT:-3}"
[[ ${INDEX_SAMPLE_COUNT} =~ ^[1-9][0-9]*$ ]] || INDEX_SAMPLE_COUNT=3
KERNEL_PACKAGE="${KERNEL_PACKAGE:-sys-kernel/gentoo-cjk-kernel}"
KERNEL_ARCH="${KERNEL_ARCH:-amd64}"
KERNEL_OVERLAY="${KERNEL_OVERLAY:-/var/lib/binhost/overlay}"
KERNEL_TREE="${KERNEL_TREE:-/var/db/repos/gentoo}"
KERNEL_SERIES_TOOL="${KERNEL_SERIES_TOOL:-/var/lib/binhost/build/kernel-series.py}"

STATUS_DIR=$(cd "$(dirname "$0")" && pwd)
GENERATION_TOOL="${GENERATION_TOOL:-}"
if [[ -z ${GENERATION_TOOL} ]]; then
    for candidate in /usr/local/lib/binhost/generation.py \
        /var/lib/binhost/build/generation.py "${STATUS_DIR}/../build/generation.py"; do
        [[ -r ${candidate} ]] && { GENERATION_TOOL="${candidate}"; break; }
    done
fi

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
COMPONENT="${COMPONENT:-}"
if [[ -z ${COMPONENT} ]]; then
    [[ -d /usr/local/lib/binhost ]] && COMPONENT=mirror
    [[ -d /var/lib/binhost/build ]] && COMPONENT=builder
fi
case ${COMPONENT} in
    mirror)  TRACKED="deploy ops build/gen-packages.py build/ebuilds.py build/verify-deps.py build/generation.py build/dep-exceptions.txt nginx" ;;
    builder) TRACKED="build ops deploy/systemd" ;;
    *)       TRACKED="" ;;
esac

check_kernel_archive() {
    local output rc line series version extra archive url code
    local -a versions missing

    [[ ${COMPONENT} == builder ]] || return
    if [[ ! -r ${KERNEL_SERIES_TOOL} ]]; then
        bad "内核归档" "缺少 ${KERNEL_SERIES_TOOL}，无法核对 overlay 版本"
        return
    fi
    if [[ ! -d ${KERNEL_OVERLAY} || ! -d ${KERNEL_TREE} ]]; then
        bad "内核归档" "overlay 或 Gentoo 主仓库不存在，无法取得应发布版本"
        return
    fi

    output=$(OVERLAY="${KERNEL_OVERLAY}" TREE="${KERNEL_TREE}" \
        PACKAGE="${KERNEL_PACKAGE}" python3 "${KERNEL_SERIES_TOOL}" 2>&1)
    rc=$?
    if (( rc != 0 )); then
        bad "内核归档" "无法取得 overlay 版本：${output:-无输出}"
        return
    fi
    mapfile -t versions <<< "${output}"
    if (( ${#versions[@]} == 0 )) || [[ -z ${versions[0]} ]]; then
        bad "内核归档" "overlay 未列出 ${KERNEL_PACKAGE} 的任何版本"
        return
    fi

    missing=()
    for line in "${versions[@]}"; do
        read -r series version extra <<< "${line}"
        if [[ -z ${series} || -z ${version} || -n ${extra} ]]; then
            bad "内核归档" "版本清单格式无法解析：${line}"
            return
        fi
        archive="${KERNEL_PACKAGE#*/}-${version}-1.${KERNEL_ARCH}.gpkg.tar"
        url="${SITE}/gentoo-cjk-kernel/${KERNEL_ARCH}/${series}/${archive}"
        code=$(curl -sSIL --max-time 20 -o /dev/null -w '%{http_code}' \
            "${url}" 2>/dev/null || true)
        [[ ${code} == 200 ]] || missing+=("${series}/${version} HTTP ${code:-无响应}")
    done
    if (( ${#missing[@]} )); then
        bad "内核归档" "缺少 overlay 版本：$(IFS='；'; echo "${missing[*]}")"
    else
        note "内核归档" "${#versions[@]} 个 overlay 版本均可下载"
    fi
}

if [[ -n ${VERSION_FILE} && -r ${VERSION_FILE} ]]; then
    here=$(tr -d ' \n' < "${VERSION_FILE}")
    there=$(curl -fsS --max-time 20 "${REPO_API}" 2>/dev/null |
            sed -n 's/^  "sha": "\([0-9a-f]\{40\}\)",$/\1/p' | head -1)
    if [[ ${here} == *-dirty ]]; then
        bad "部署版本" "${here:0:8} 是从未提交的工作树装的，无法核对"
    elif [[ ! ${here} =~ ^[0-9a-f]{40}$ ]]; then
        bad "部署版本" "VERSION 不是提交号：${here:0:16}"
    elif [[ -z ${there} ]]; then
        bad "部署版本" "${here:0:8}，无法获取目标版本，本次未能核对"
    elif [[ ${here} == "${there}" ]]; then
        note "部署版本" "${here:0:8}，与目标版本一致"
    elif [[ -z ${TRACKED} ]]; then
        bad "部署版本" "已部署 ${here:0:8}，目标版本 ${there:0:8}"
    else
        changed=$(curl -fsS --max-time 25 \
            "https://api.github.com/repos/gentoo-zh/binhost/compare/${here}...${there}" 2>/dev/null |
            sed -n 's/^      "filename": "\(.*\)",$/\1/p')
        hit=""
        for path in ${TRACKED}; do
            grep -q "^${path}" <<< "${changed}" && { hit="${path}"; break; }
        done
        if [[ -z ${changed} ]]; then
            bad "部署版本" "已部署 ${here:0:8}，目标版本 ${there:0:8}，无法获取两者差异，不能判断本机是否落后"
        elif [[ -n ${hit} ]]; then
            bad "部署版本" "已部署 ${here:0:8}，目标版本 ${there:0:8}，${hit} 已变更"
        else
            note "部署版本" "${here:0:8}，本机安装的部分与 ${there:0:8} 无差异"
        fi
    fi
else
    bad "部署版本" "缺少 VERSION，安装时未记录提交号"
fi

check_kernel_archive

site_syncing() { [[ -e ${SITE_LOCK} ]] && ! flock -n "${SITE_LOCK}" true 2>/dev/null; }

check_site_sync() {
    local fetched age_h here_site marked drift pages f

    fetched=$(stat -c %Y "${SITE_WORK}/.git/FETCH_HEAD" 2>/dev/null || echo 0)
    age_h=$(( ($(date +%s) - fetched) / 3600 ))

    if (( fetched == 0 )); then
        bad "站点同步" "${SITE_WORK}/.git/FETCH_HEAD 不存在，同步从未执行"
        return
    fi
    if (( age_h >= SITE_STALE_H )); then
        bad "站点同步" "上次拉取在 ${age_h} 小时前，五分钟一次的同步已停止"
        return
    fi
    # The revision and the comparisons below have to come from a tree nobody is
    # rewriting, so the lock is tested before them and again after. Reading
    # first left a window as wide as one diff -rq plus one cmp per page.
    if site_syncing; then
        note "站点同步" "同步正在执行，本次不比对仓库副本与已发布内容"
        return
    fi

    here_site=$(git -C "${SITE_WORK}" rev-parse HEAD 2>/dev/null)
    marked=$(cat "${SITE_WORK}/.synced" 2>/dev/null || true)
    drift=$(diff -rq "${SITE_WORK}/site/assets" "${SITE_DEST}/assets" 2>&1 | wc -l)
    pages=0
    for f in "${SITE_WORK}"/site/*.html; do
        cmp -s "${f}" "${SITE_DEST}/$(basename "${f}")" || pages=$((pages + 1))
    done

    if site_syncing; then
        note "站点同步" "同步正在执行，本次不比对仓库副本与已发布内容"
    elif [[ ! ${here_site} =~ ^[0-9a-f]{40}$ ]]; then
        bad "站点同步" "无法解析 ${SITE_WORK} 的版本：${here_site:-无输出}"
    elif [[ ${marked} != "${here_site}" ]]; then
        bad "站点同步" "仓库副本在 ${here_site:0:8}，上次完成的是 ${marked:0:8}，最近一次未完成"
    elif (( drift )); then
        bad "站点同步" "assets 有 ${drift} 处与仓库副本不一致，rsync 未完成"
    elif (( pages )); then
        bad "站点同步" "${pages} 个页面与仓库副本不一致，rsync 未完成"
    elif [[ ! -r ${SITE_DEST}/gentoo-zh-binhost.asc ]]; then
        bad "站点同步" "发布目录未包含公钥，用户按站点第 1 步无法获取它"
    elif ! cmp -s "${SITE_WORK}/site/gentoo-zh-binhost.asc" "${SITE_DEST}/gentoo-zh-binhost.asc"; then
        bad "站点同步" "仓库里的公钥与已发布的不一致，指纹守卫可能拦下了它"
    else
        note "站点同步" "${here_site:0:8}，${age_h} 小时内已拉取"
    fi
}

if [[ ! -d ${SITE_WORK}/.git && -d ${SITE_DEST} && -e ${SITE_DEST}/index.html ]]; then
    bad "站点同步" "${SITE_WORK} 不是仓库副本，而 ${SITE_DEST} 里有站点内容"
elif [[ -d ${SITE_WORK}/.git ]]; then
    check_site_sync
fi

if [[ -d ${SIGNING_GNUPGHOME} ]]; then
    if [[ -z ${SIGNING_KEY:-} ]]; then
        SIGNING_KEY=$(sed -n 's/^Environment=SIGNING_KEY=//p' \
            /etc/systemd/system/binhost-build.service 2>/dev/null | tail -1)
    fi
    if [[ -z ${SIGNING_KEY:-} ]]; then
        bad "签名密钥" "无法确定应使用的密钥指纹，SIGNING_KEY 未设置"
    else
        secret=$(sudo gpg --homedir "${SIGNING_GNUPGHOME}" --with-colons \
                 --list-secret-keys "${SIGNING_KEY}" 2>/dev/null)
        gpg_rc=$?
        caps=$(awk -F: '/^sec:/{print $12; exit}' <<< "${secret}")
        trust=$(awk -F: '/^sec:/{print $2; exit}' <<< "${secret}")
        expiry=$(awk -F: '/^sec:/{print $7; exit}' <<< "${secret}")
        if (( gpg_rc != 0 )) || ! grep -q '^sec:' <<< "${secret}"; then
            bad "签名密钥" "${SIGNING_GNUPGHOME} 未包含 ${SIGNING_KEY:0:8} 的私钥"
        elif [[ ${trust} == r ]]; then
            bad "签名密钥" "${SIGNING_KEY:0:8} 已撤销"
        elif [[ ${caps} != *s* ]]; then
            bad "签名密钥" "${SIGNING_KEY:0:8} 没有签名能力（capabilities=${caps:-无}）"
        elif [[ -n ${expiry} && ${expiry} != 0 ]]; then
            left=$(( (expiry - $(date +%s)) / 86400 ))
            if (( left < KEY_WARN_DAYS )); then
                bad "签名密钥" "${SIGNING_KEY:0:8} 将在 ${left} 天后过期"
            else
                note "签名密钥" "${SIGNING_KEY:0:8}，${left} 天后过期"
            fi
        else
            note "签名密钥" "${SIGNING_KEY:0:8}，无过期时间"
        fi
    fi
else
    note "签名密钥" "该目录不存在"
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
        bad "TLS 证书" "${left} 天后过期"
    else
        note "TLS 证书" "${left} 天后过期"
    fi
else
    bad "TLS 证书" "无法读取"
fi

check_channel_index() {
    local label=$1 root=$2 tmp name ts n age hash start checks i index path code
    local -a paths

    tmp=$(mktemp -d)
    for name in Packages Packages.gz installed.txt official.txt source.txt generation.json; do
        if ! curl -fsS --max-time 20 "${SITE}${root}/${name}" \
            > "${tmp}/${name}" 2>/dev/null; then
            bad "${label} 同代清单" "无法获取 ${name}"
            rm -rf "${tmp}"
            return
        fi
    done
    if [[ -z ${GENERATION_TOOL} ]] ||
       ! python3 "${GENERATION_TOOL}" verify "${tmp}" >/dev/null 2>&1; then
        bad "${label} 同代清单" "generation.json 与索引或快照不一致"
        rm -rf "${tmp}"
        return
    fi
    note "${label} 同代清单" "验证通过"

    ts=$(awk '/^TIMESTAMP: /{print $2; exit}' "${tmp}/Packages")
    n=$(awk '/^PACKAGES: /{print $2; exit}' "${tmp}/Packages")
    if [[ ! ${ts} =~ ^[0-9]+$ ]]; then
        bad "${label} 索引" "TIMESTAMP 无法解析"
    else
        age=$(( ( $(date +%s) - ts ) / 86400 ))
        if (( age >= INDEX_MAX_AGE_D )); then
            bad "${label} 索引" "${age} 天未更新（超过 ${INDEX_MAX_AGE_D} 天）"
        elif [[ ! ${n} =~ ^[0-9]+$ ]] || (( n == 0 )); then
            bad "${label} 索引" "未包含任何软件包"
        else
            note "${label} 索引" "${n} 个包，${age} 天前"
        fi
    fi

    mapfile -t paths < <(awk '/^PATH: /{print $2}' "${tmp}/Packages")
    if (( ${#paths[@]} == 0 )); then
        bad "${label} 取包" "索引未列出 PATH"
        rm -rf "${tmp}"
        return
    fi

    checks=${INDEX_SAMPLE_COUNT}
    (( checks > ${#paths[@]} )) && checks=${#paths[@]}
    hash=$(sha256sum "${tmp}/generation.json" | cut -c1-8)
    start=$(( 16#${hash} % ${#paths[@]} ))
    for ((i = 0; i < checks; i++)); do
        index=$(( (start + i * ${#paths[@]} / checks) % ${#paths[@]} ))
        path=${paths[index]}
        code=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -L \
               "${SITE}${root}/${path}" 2>/dev/null)
        if [[ ${code} != 200 ]]; then
            bad "${label} 取包抽查" "${path} 返回 HTTP ${code}"
            rm -rf "${tmp}"
            return
        fi
    done
    note "${label} 取包抽查" "${checks} 个均可下载"
    rm -rf "${tmp}"
}

check_channel_index stable "/binpkgs/${TAG}"
check_channel_index unstable "/unstable/binpkgs/${TAG}"

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
            bad "distfiles" "${dage} 小时未同步（超过 ${DIST_MAX_AGE_H} 小时）"
        else
            note "distfiles" "${dn} 个文件，${dage} 小时前"
        fi
    fi
fi

if ! command -v node_exporter >/dev/null 2>&1; then
    note "node_exporter" "本机没有安装"
elif ! curl -fsS --max-time 10 -o /dev/null "http://127.0.0.1:${EXPORTER_PORT}/metrics"; then
    bad "node_exporter" "本机 ${EXPORTER_PORT} 未响应"
else
    rules=$(sudo -n nft list chain inet filter input 2>/dev/null)
    if [[ -z ${rules} ]]; then
        note "node_exporter" "应答正常（防火墙不由这里管）"
    elif [[ ${rules} != *"dport ${EXPORTER_PORT}"* ]]; then
        bad "node_exporter" "防火墙没有放行 ${EXPORTER_PORT} 的规则"
    else
        if ! set_out=$(sudo -n nft list set inet filter monitor_hosts 2>/dev/null); then
            bad "node_exporter" "无法读取 monitor_hosts 集合"
        else
            monitors=$(grep -Eo '[0-9]+(\.[0-9]+){3}' <<< "${set_out}" | wc -l)
            want=0
            [[ -r ${MONITORS_FILE} ]] &&
                want=$(grep -Eo '[0-9]+(\.[0-9]+){3}' "${MONITORS_FILE}" | wc -l)
            if (( monitors > 0 )); then
                note "node_exporter" "检查通过，放行 ${monitors} 个抓取源"
            elif (( want > 0 )); then
                bad "node_exporter" "安装时配置了 ${want} 个抓取源，当前集合为空"
            else
                bad "node_exporter" "${EXPORTER_PORT} 已启动且防火墙已放行，但抓取源清单为空，没有任何监控能取得指标"
            fi
        fi
    fi
fi


check_build_status() {
    local label=$1 file=$2 job jstate jphase jts jprog jage page
    job=$(curl -fsS --max-time 15 "${SITE}/${file}" 2>/dev/null)
    if [[ -z ${job} ]]; then
        bad "${label} 构建状态" "无法获取 ${file}"
        return
    fi

    jstate=$(grep -o '"state":"[a-z]*"' <<< "${job}" | cut -d'"' -f4)
    jphase=$(grep -o '"phase":"[a-z-]*"' <<< "${job}" | cut -d'"' -f4)
    jts=$(grep -o '"generated":[0-9]*' <<< "${job}" | cut -d: -f2)
    # progress_at comes from the build itself; generated is only when the
    # watcher last pushed. They diverge when the watcher outlives the build.
    jprog=$(grep -o '"progress_at":[0-9]*' <<< "${job}" | cut -d: -f2)
    [[ ${jprog} =~ ^[0-9]+$ ]] || jprog="${jts}"
    if [[ ! ${jts} =~ ^[0-9]+$ ]]; then
        bad "${label} 构建状态" "generated 无法解析"
        return
    fi

    jage=$(( ( $(date +%s) - jts ) / 3600 ))
    page=$(( ( $(date +%s) - jprog ) / 3600 ))
    if [[ ${jstate} != "running" && ${jstate} != "done" && ${jstate} != "failed" ]]; then
        bad "${label} 构建状态" "state 无法解析：${jstate:-缺失}"
    elif [[ ${jstate} == failed ]]; then
        bad "${label} 构建状态" "上次构建失败（${jage} 小时前）"
    elif [[ ${jstate} == running ]] && (( page >= BUILD_STALE_H )); then
        bad "${label} 构建状态" "${jphase:-未知} 阶段已 ${page} 小时没有进展"
    elif [[ ${jstate} == running ]] && (( jage >= BUILD_STALE_H )); then
        bad "${label} 构建状态" "进度状态已 ${jage} 小时未更新"
    elif (( jage >= HEARTBEAT_MAX_H )); then
        bad "${label} 构建状态" "${jage} 小时未更新（阈值 ${HEARTBEAT_MAX_H}h）"
    else
        note "${label} 构建状态" "${jstate:-未知}，${jage} 小时前"
    fi
}

check_build_status stable build-status.json
check_build_status unstable build-status-unstable.json

# The scheduled run owns this file, so testing the directory said yes while the
# write said no: another user could create the file here but not overwrite the
# one root already left. That printed a bare Permission denied and looked like a
# fault. Try the write and say plainly when it did not happen.
if [[ -d $(dirname "${HEARTBEAT}") ]] && ! date +%s 2>/dev/null > "${HEARTBEAT}"; then
    note "心跳写入" "本次未更新 ${HEARTBEAT}，由排程执行的那次负责"
fi

stamp=$(curl -fsS --max-time 15 "${SITE}/.health" 2>/dev/null | tr -dc '0-9')
if [[ -z ${stamp} ]]; then
    bad "心跳" "无法获取 ${SITE}/.health"
else
    age_h=$(( ( $(date +%s) - stamp ) / 3600 ))
    if (( age_h >= HEARTBEAT_MAX_H )); then
        bad "心跳" "${age_h} 小时未更新（阈值 ${HEARTBEAT_MAX_H} 小时）"
    else
        note "心跳" "${age_h} 小时前"
    fi
fi


if (( problems > 0 )) && [[ ! -r ${ALERT_CONF} ]]; then
    echo "!! 有 ${problems} 项未通过，但 ${ALERT_CONF} 无法读取，告警传送失败" >&2
fi

STATE_FILE="${STATE_FILE:-/var/lib/binhost/status-state}"
COOLDOWN_H="${COOLDOWN_H:-24}"

fingerprint=""
if (( problems > 0 )); then
    fingerprint=$(printf '%s\n' "${failures[@]}" | sed 's/[0-9]\+/N/g' | sort |
                  sha256sum | cut -c1-16)
fi

prev_fp=""
prev_at=0
if [[ -r ${STATE_FILE} ]]; then
    read -r prev_fp prev_at < "${STATE_FILE}" 2>/dev/null || { prev_fp=""; prev_at=0; }
    [[ ${prev_at} =~ ^[0-9]+$ ]] || prev_at=0
fi

now=$(date +%s)
kind=none
if (( problems > 0 )); then
    if [[ ${fingerprint} != "${prev_fp}" ]]; then
        kind=new
    elif (( now - prev_at >= COOLDOWN_H * 3600 )); then
        kind=repeat
    fi
elif [[ -n ${prev_fp} ]]; then
    kind=recovered
fi

save_state() {
    local fp="$1" at="$2" tmp
    tmp="${STATE_FILE}.new"
    mkdir -p "$(dirname "${STATE_FILE}")" 2>/dev/null || true
    if printf '%s %s\n' "${fp}" "${at}" > "${tmp}" 2>/dev/null; then
        mv -f "${tmp}" "${STATE_FILE}" 2>/dev/null ||
            echo "!! 无法写入 ${STATE_FILE}，去重状态未保存" >&2
    else
        echo "!! 无法写入 ${STATE_FILE}，去重状态未保存" >&2
    fi
}

sent=0
if [[ ${kind} != none ]] && [[ ${BINHOST_ALERT:-} == 1 ]] && [[ -r ${ALERT_CONF} ]]; then
    # shellcheck source=/dev/null
    . "${ALERT_CONF}"
    if [[ -z ${TELEGRAM_TOKEN:-} || -z ${TELEGRAM_CHAT:-} ]]; then
        echo "!!! ${ALERT_CONF} 缺 TELEGRAM_TOKEN 或 TELEGRAM_CHAT，本次告警未发出" >&2
    fi
    if [[ -n ${TELEGRAM_TOKEN:-} && -n ${TELEGRAM_CHAT:-} ]]; then
        if [[ ${kind} == recovered ]]; then
            text="binhost 检查已全部通过（$(hostname)）"
        else
            case ${kind} in
                new)    text="binhost 检查未通过（$(hostname)）:" ;;
                repeat) text="binhost 检查仍未通过（$(hostname)，已持续 $(( (now - prev_at) / 3600 )) 小时）:" ;;
            esac
            for f in "${failures[@]}"; do
                text+=$'\n'"• ${f}"
            done
        fi
        if curl -fsS --max-time 20 -o /dev/null \
            --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
            --data-urlencode "text=${text}" \
            --data "disable_notification=false" \
            --config - <<EOF
url = "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage"
EOF
        then
            sent=1
        else
            echo "!!! 告警发送失败" >&2
        fi
    fi
fi

if (( sent )); then
    if (( problems > 0 )); then
        save_state "${fingerprint}" "${now}"
    else
        save_state "" "${now}"
    fi
fi

if (( problems > 0 )); then
    if (( sent )); then
        exit "${EXIT_ALERTED}"
    fi
    if [[ ${kind} == none ]]; then
        echo "  （与上次相同的故障，${COOLDOWN_H} 小时内不重复通知）"
        exit "${EXIT_SUPPRESSED}"
    fi
    exit 1
fi
exit 0
