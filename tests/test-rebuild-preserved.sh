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

# A package that links the preserved library cannot clear it when it comes back
# from a binary package built against the old one, so the set has to be built
# from source. The stubs record what was asked for and answer what portageq
# would answer.
probe() {
    local still="$1" d rc
    d=$(mktemp -d)
    mkdir -p "${d}/bin"
    cat > "${d}/bin/emerge" <<EOF2
#!/bin/bash
printf '%s\n' "\$*" >> "${d}/emerge.args"
exit 0
EOF2
    cat > "${d}/bin/portageq" <<EOF2
#!/bin/bash
if [ "${still}" = yes ]; then
    echo "sys-libs/binutils-libs-2.46.1 /usr/lib64/libbfd-2.46.0.so"
    exit 0
fi
exit 1
EOF2
    chmod +x "${d}/bin/emerge" "${d}/bin/portageq"
    PATH="${d}/bin:${PATH}" bash "${ROOT}/build/rebuild-preserved.sh" "${d}/log" \
        > "${d}/out" 2>&1
    rc=$?
    printf '%s|%s|%s\n' "${rc}" \
        "$(grep -c -- '--usepkg=n' "${d}/emerge.args" 2>/dev/null)" \
        "$(grep -c 'preserved-rebuild' "${d}/emerge.args" 2>/dev/null)"
    rm -rf "${d}"
}

echo "== 保留库的使用者必须从源码重建"

IFS='|' read -r rc source_only called <<< "$(probe no)"
ok "清干净时退出码 0" "${rc}" "0"
ok "呼叫了 @preserved-rebuild" "${called}" "1"
ok "不重用二进位包" "${source_only}" "1"

IFS='|' read -r rc source_only called <<< "$(probe yes)"
ok "仍有保留库时以非零退出" "${rc}" "1"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
