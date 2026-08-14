#!/bin/bash

set -euo pipefail

DEST="${DEST:-/srv/pub/gentoo-cjk-livecd}"
TEMP_DIR="${TEMP_DIR:-${DEST}.tmp}"
API_URL="${API_URL:-https://api.github.com/repos/gentoo-zh/gentoo-cjk-livecd/releases?per_page=2}"
DOWNLOAD_BASE="${DOWNLOAD_BASE:-}"
MAX_RETIRE="${MAX_RETIRE:-2}"
# Headroom left after the download. /srv is served, so filling it to the last
# byte breaks more than this sync.
MIN_FREE_BYTES="${MIN_FREE_BYTES:-5368709120}"

fail() {
    echo "!! $1" >&2
    exit 1
}

[[ ${MAX_RETIRE} =~ ^[0-9]+$ ]] || fail "MAX_RETIRE 不是非负整数"
[[ ${MIN_FREE_BYTES} =~ ^[0-9]+$ ]] || fail "MIN_FREE_BYTES 不是非负整数"

api_work=$(mktemp -d)
work=""
cleanup() {
    [[ -z ${work} ]] || rm -rf "${work}"
    rm -rf "${api_work}"
}
trap cleanup EXIT

api_json="${api_work}/releases.json"
manifest="${api_work}/manifest"
if ! curl -fsSL --max-time 60 "${API_URL}" -o "${api_json}"; then
    fail "无法获取 GitHub release 清单，保留现有档案"
fi

if ! python3 - "${api_json}" "${manifest}" <<'PY'
import json
import pathlib
import re
import sys

try:
    releases = json.loads(pathlib.Path(sys.argv[1]).read_text())
except (OSError, json.JSONDecodeError):
    sys.exit(1)
if not isinstance(releases, list) or len(releases) < 2:
    sys.exit(1)

rows = []
for release in releases[:2]:
    if not isinstance(release, dict):
        sys.exit(1)
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", tag):
        sys.exit(1)
    assets = release.get("assets")
    if not isinstance(assets, list):
        sys.exit(1)
    by_name = {a.get("name"): a for a in assets if isinstance(a, dict)}
    prefix = f"install-amd64-cjk-minimal-{tag}.iso"
    # The ISO is verified against its own .sha256, so that file has to be
    # on disk first; fetching the ISO before it costs a 944 MB retry.
    required = [prefix + ".sha256", prefix + ".CONTENTS.gz",
                prefix + ".DIGESTS", prefix]
    if any(name not in by_name for name in required):
        sys.exit(1)
    for name in required:
        asset = by_name[name]
        url = asset.get("browser_download_url")
        size = asset.get("size")
        digest = asset.get("digest") or ""
        if not isinstance(url, str) or not url or not isinstance(size, int) or size < 0:
            sys.exit(1)
        if not isinstance(digest, str):
            digest = ""
        rows.append((tag, name, url, str(size), digest))

pathlib.Path(sys.argv[2]).write_text("\n".join("\t".join(row) for row in rows) + "\n")
PY
then
    fail "GitHub release 清单为空或格式不完整，保留现有档案"
fi

mkdir -p "${DEST}" "${TEMP_DIR}"
[[ $(stat -c %d "${TEMP_DIR}") == "$(stat -c %d "${DEST}")" ]] ||
    fail "${TEMP_DIR} 与 ${DEST} 不在同一个文件系统"
work=$(mktemp -d "${TEMP_DIR}/.livecd-sync.XXXXXX")

# The published file leads with a "# SHA256 HASH" comment line, so the first
# non-empty line is not the checksum. Both callers read it through here: fixing
# only one of them left the second run re-downloading every ISO.
sha256_of() {
    awk '$1 ~ /^[0-9a-fA-F]{64}$/ { print $1; exit }' "$1" 2>/dev/null || true
}

asset_ok() {
    local path=$1 name=$2 size=$3 digest=$4
    [[ -f ${path} ]] || return 1
    [[ ${size} == 0 || $(stat -c %s "${path}") == "${size}" ]] || return 1
    if [[ ${digest} == sha256:* ]]; then
        [[ $(sha256sum "${path}" | awk '{print $1}') == "${digest#sha256:}" ]] || return 1
    fi
    if [[ ${name} == *.iso ]]; then
        local checksum
        checksum=$(sha256_of "${path}.sha256")
        [[ ${checksum} =~ ^[0-9a-fA-F]{64}$ ]] || return 1
        [[ $(sha256sum "${path}" | awk '{print $1}') == "${checksum}" ]] || return 1
    elif [[ ${name} == *.sha256 ]]; then
        grep -Eq '^[[:space:]]*[0-9a-fA-F]{64}[[:space:]]+' "${path}" || return 1
    fi
}

available=$(df -Pk "${DEST}" | awk 'NR == 2 {print $4 * 1024}')
[[ ${available} =~ ^[0-9]+$ ]] || fail "无法取得 ${DEST} 所在文件系统的可用空间"
needed=0
while IFS=$'\t' read -r tag name url size digest; do
    path="${DEST}/${tag}/${name}"
    if ! asset_ok "${path}" "${name}" "${size}" "${digest}"; then
        needed=$((needed + size))
    fi
done < "${manifest}"
if (( available < needed + MIN_FREE_BYTES )); then
    fail "磁盘可用空间不足：需要至少 $((needed + MIN_FREE_BYTES)) 字节，现有 ${available} 字节"
fi

download_asset() {
    local tag=$1 name=$2 url=$3 size=$4 digest=$5 dir path part attempt checksum
    dir="${DEST}/${tag}"
    path="${dir}/${name}"
    mkdir -p "${dir}"
    asset_ok "${path}" "${name}" "${size}" "${digest}" && return 0
    [[ -n ${DOWNLOAD_BASE} ]] && url="${DOWNLOAD_BASE}/${tag}/${name}"
    for attempt in 1 2; do
        part="${work}/${tag}.${name}.${attempt}.part"
        rm -f "${part}"
        if ! curl -fsSL --max-time 1800 "${url}" -o "${part}"; then
            continue
        fi
        [[ ${size} == 0 || $(stat -c %s "${part}") == "${size}" ]] || continue
        if [[ ${digest} == sha256:* ]]; then
            [[ $(sha256sum "${part}" | awk '{print $1}') == "${digest#sha256:}" ]] || continue
        fi
        if [[ ${name} == *.sha256 ]]; then
            grep -Eq '^[[:space:]]*[0-9a-fA-F]{64}[[:space:]]+' "${part}" || continue
        fi
        if [[ ${name} == *.iso ]]; then
            checksum=$(sha256_of "${dir}/${name}.sha256")
            [[ ${checksum} =~ ^[0-9a-fA-F]{64}$ ]] || continue
            [[ $(sha256sum "${part}" | awk '{print $1}') == "${checksum}" ]] || continue
        fi
        mv -f "${part}" "${path}"
        return 0
    done
    rm -f "${part}"
    echo "!! ${tag}/${name} 下载或校验失败，保留原有档案" >&2
    return 1
}

failure=0
while IFS=$'\t' read -r tag name url size digest; do
    [[ ${name} == *.iso ]] && continue
    download_asset "${tag}" "${name}" "${url}" "${size}" "${digest}" || failure=1
done < "${manifest}"
while IFS=$'\t' read -r tag name url size digest; do
    [[ ${name} == *.iso ]] || continue
    download_asset "${tag}" "${name}" "${url}" "${size}" "${digest}" || failure=1
done < "${manifest}"
(( failure == 0 )) || exit 1

mapfile -t old_dirs < <(find "${DEST}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | while read -r d; do
    grep -qxF "${d}" <(cut -f1 "${manifest}") || printf '%s\n' "${d}"
done)
if (( ${#old_dirs[@]} > MAX_RETIRE )); then
    fail "待退役目录 ${#old_dirs[@]} 个，超过上限 ${MAX_RETIRE}，一个都不删除"
fi
for d in "${old_dirs[@]}"; do
    # DEST as well as the tag: an empty DEST would turn this into rm -rf /<tag>.
    [[ -n ${d} ]] && rm -rf -- "${DEST:?}/${d}"
done

echo "$(date '+%F %T') 已同步最新两个 LiveCD release"
