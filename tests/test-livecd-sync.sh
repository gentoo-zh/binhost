#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

mkdir -p "${WORK}/bin" "${WORK}/payload"
TAGS=(20260813T073053Z 20260810T120000Z)
DOWNLOAD_LOG="${WORK}/downloads.log"
API_JSON="${WORK}/api.json"

make_payload() {
    local tag=$1 name=$2 content=$3
    printf '%s' "${content}" > "${WORK}/payload/${tag}/${name}"
}

make_release() {
    local tag=$1 iso_name="install-amd64-cjk-minimal-${1}.iso"
    mkdir -p "${WORK}/payload/${tag}"
    make_payload "${tag}" "${iso_name}.CONTENTS.gz" "contents-${tag}\n"
    make_payload "${tag}" "${iso_name}.DIGESTS" "digest-${tag}\n"
    printf 'iso-%s\n' "${tag}" > "${WORK}/payload/${tag}/${iso_name}"
    sha=$(sha256sum "${WORK}/payload/${tag}/${iso_name}" | awk '{print $1}')
    # The real file leads with a comment line; a fixture without it let a
    # checksum parser that reads the first line pass the tests and fail on the
    # published ISO.
    printf '# SHA256 HASH\n%s  %s\n' "${sha}" "${iso_name}" \
        > "${WORK}/payload/${tag}/${iso_name}.sha256"
}

for tag in "${TAGS[@]}"; do make_release "${tag}"; done

python3 - "${WORK}/payload" "${API_JSON}" "${TAGS[@]}" <<'PY'
import json
import pathlib
import sys

payload = pathlib.Path(sys.argv[1])
releases = []
for tag in sys.argv[3:]:
    assets = []
    for path in sorted((payload / tag).iterdir()):
        assets.append({
            "name": path.name,
            "size": path.stat().st_size,
            "browser_download_url": f"https://download.invalid/{tag}/{path.name}",
        })
    releases.append({"tag_name": tag, "assets": assets})
pathlib.Path(sys.argv[2]).write_text(json.dumps(releases))
PY

cat > "${WORK}/bin/curl" <<'EOF'
#!/bin/bash
set -euo pipefail
url=""
out=""
for arg in "$@"; do
    if [[ ${arg} == http* ]]; then url=${arg}; fi
done
prev=""
for arg in "$@"; do
    if [[ ${prev} == -o ]]; then out=${arg}; fi
    prev=${arg}
done
[[ -n ${out} ]] || exit 2
if [[ ${CURL_FAIL_API:-0} == 1 && ${url} == *api.github.com* ]]; then exit 22; fi
if [[ ${url} == *api.github.com* ]]; then
    cp "${API_JSON}" "${out}"
    exit 0
fi
name=${url##*/}
tag=$(basename "$(dirname "${url}")")
printf '%s/%s\n' "${tag}" "${name}" >> "${DOWNLOAD_LOG}"
source="${WORK}/payload/${tag}/${name}"
if [[ ${FAIL_ISO:-0} == 1 && ${name} == *.iso ]]; then
    printf 'bad iso\n' > "${out}"
else
    cp "${source}" "${out}"
fi
EOF
chmod +x "${WORK}/bin/curl"

run_sync() {
    export WORK API_JSON DOWNLOAD_LOG
    PATH="${WORK}/bin:${PATH}" \
        FAIL_ISO="${FAIL_ISO:-0}" CURL_FAIL_API="${CURL_FAIL_API:-0}" \
        DEST="${WORK}/dest" TEMP_DIR="${WORK}/temp" API_URL="https://api.github.com/releases" \
        MIN_FREE_BYTES="${MIN_FREE_BYTES:-0}" bash "${ROOT}/deploy/livecd-sync.sh"
}

assert_assets() {
    local tag=$1 iso="install-amd64-cjk-minimal-${1}.iso"
    [[ -d "${WORK}/dest/${tag}" ]]
    for name in "${iso}" "${iso}.CONTENTS.gz" "${iso}.DIGESTS" "${iso}.sha256"; do
        [[ -f "${WORK}/dest/${tag}/${name}" ]] || return 1
    done
}

run_sync >/dev/null
for tag in "${TAGS[@]}"; do assert_assets "${tag}"; done
echo "  ✓ 首次同步建立两个 release 目录及四个资产"

downloads=$(wc -l < "${DOWNLOAD_LOG}")
run_sync >/dev/null
[[ $(wc -l < "${DOWNLOAD_LOG}") == "${downloads}" ]]
echo "  ✓ 校验通过的资产不会重新下载"

iso_before=()
for tag in "${TAGS[@]}"; do
    iso="install-amd64-cjk-minimal-${tag}.iso"
    iso_before+=("$(grep -c "^${tag}/${iso}$" "${DOWNLOAD_LOG}" || true)")
done
rm -rf "${WORK}/dest"
if FAIL_ISO=1 run_sync >/dev/null 2>&1; then
    echo "  ✗ ISO 校验失败时应当返回错误"
    exit 1
fi
for i in "${!TAGS[@]}"; do
    tag=${TAGS[${i}]}
    iso="install-amd64-cjk-minimal-${tag}.iso"
    [[ ! -e "${WORK}/dest/${tag}/${iso}" ]]
    [[ $(grep -c "^${tag}/${iso}$" "${DOWNLOAD_LOG}") == $(( iso_before[i] + 2)) ]]
done
echo "  ✓ ISO 校验失败时不留下正式文件名"

before=$(wc -l < "${DOWNLOAD_LOG}")
rm -rf "${WORK}/dest"
if MIN_FREE_BYTES=999999999999 run_sync >/dev/null 2>&1; then
    echo "  ✗ 磁盘空间不足时应当返回错误"
    exit 1
fi
[[ $(wc -l < "${DOWNLOAD_LOG}") == "${before}" ]]
echo "  ✓ 磁盘空间不足时不会开始下载"

run_sync >/dev/null
mkdir -p "${WORK}/dest/old-one"
printf old > "${WORK}/dest/old-one/file"
run_sync >/dev/null
[[ ! -e "${WORK}/dest/old-one" ]]
echo "  ✓ 第三个旧 tag 会被移除"

for old in old-a old-b old-c; do mkdir -p "${WORK}/dest/${old}"; done
if run_sync >/dev/null 2>&1; then
    echo "  ✗ 超过 MAX_RETIRE 时应当返回错误"
    exit 1
fi
for old in old-a old-b old-c; do [[ -d "${WORK}/dest/${old}" ]]; done
echo "  ✓ 超过 MAX_RETIRE 时旧目录全部保留"

before=$(find "${WORK}/dest" -mindepth 1 -maxdepth 2 -type f -printf '%P\n' | sort)
if CURL_FAIL_API=1 run_sync >/dev/null 2>&1; then
    echo "  ✗ API 失败时应当返回错误"
    exit 1
fi
after=$(find "${WORK}/dest" -mindepth 1 -maxdepth 2 -type f -printf '%P\n' | sort)
[[ ${before} == "${after}" ]]
for old in old-a old-b old-c; do [[ -d "${WORK}/dest/${old}" ]]; done
echo "  ✓ API 失败时现状不变且不退役目录"
