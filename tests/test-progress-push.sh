#!/bin/bash

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass=0
fail=0

ok() {
    if [[ $2 == "$3" ]]; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      得到 %s，应为 %s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

# push() is taken out of build-progress.sh so the assertions bind to the
# deployed file, and the ssh stub runs the remote command for real against a
# temporary directory. Only the hop is faked; the rename dance is not.
# shellcheck disable=SC1090
source <(sed -n '/^push()/,/^}/p' "${ROOT}/build/build-progress.sh")

setup() {
    local d="$1"
    mkdir -p "${d}/site" "${d}/bin"
    cat > "${d}/bin/ssh" <<EOF
#!/bin/bash
# \$1 is the host, \$2 is the command line. Slow mv turns an unsynchronised
# rename into a collision every run instead of once in a hundred.
PATH="${d}/slow:\${PATH}" exec sh -c "\$2"
EOF
    mkdir -p "${d}/slow"
    cat > "${d}/slow/mv" <<EOF
#!/bin/sh
sleep "\${MV_DELAY:-0}"
exec /usr/bin/mv "\$@"
EOF
    chmod +x "${d}/bin/ssh" "${d}/slow/mv"
}

# Two pushes overlap: the second starts while the first is inside its rename.
collide() {
    local d rc_a rc_b
    d=$(mktemp -d)
    setup "${d}"

    # push() reads these from the environment, and the stub mv reads MV_DELAY.
    export PATH="${d}/bin:${PATH}" MV_DELAY=1
    export REMOTE=stub SITE_ROOT="${d}/site" OUT=build-status.json

    ( printf '{"state":"running"}\n' | push; echo "$?" > "${d}/rc-a" ) &
    local first=$!
    sleep 0.2
    ( printf '{"state":"done"}\n' | push; echo "$?" > "${d}/rc-b" ) &
    wait "${first}" "$!"

    rc_a=$(cat "${d}/rc-a" 2>/dev/null)
    rc_b=$(cat "${d}/rc-b" 2>/dev/null)
    printf '%s|%s|%s|%s|%s\n' \
        "${rc_a}" "${rc_b}" \
        "$(python3 -c 'import json,sys
try:
    json.load(open(sys.argv[1])); print("valid")
except Exception:
    print("invalid")' "${d}/site/build-status.json" 2>/dev/null)" \
        "$(find "${d}/site" -name '.build-status.json*' | wc -l)" \
        "$(stat -c %a "${d}/site/build-status.json" 2>/dev/null)"
    rm -rf "${d}"
}

echo "== 两次推送重叠时都要成功"
IFS='|' read -r rc_a rc_b valid leftovers mode <<< "$(collide)"
ok "先发的那次成功" "${rc_a}" "0"
ok "后发的那次成功" "${rc_b}" "0"
ok "落地的档案是完整 JSON" "${valid}" "valid"
ok "没有留下临时档" "${leftovers}" "0"
ok "落地的档案可被读取" "${mode}" "644"

echo
echo "== 远端失败时如实回报"
probe_fail() {
    local d out rc
    d=$(mktemp -d)
    setup "${d}"
    cat > "${d}/bin/ssh" <<'EOF'
#!/bin/bash
exit 255
EOF
    chmod +x "${d}/bin/ssh"
    export PATH="${d}/bin:${PATH}"
    export REMOTE=stub SITE_ROOT="${d}/site" OUT=build-status.json
    out=$(printf '{}\n' | push 2>&1)
    rc=$?
    printf '%s|%s\n' "${rc}" "$([[ ${out} == *未能发送* ]] && echo yes)"
    rm -rf "${d}"
}
IFS='|' read -r rc said <<< "$(probe_fail)"
ok "推送失败返回非零" "${rc}" "1"
ok "推送失败有说明" "${said}" "yes"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
