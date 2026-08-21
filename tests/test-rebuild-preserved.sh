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
    cat > "${d}/consumers" <<EOF2
#!/usr/bin/env python3
import sys
if "${still}" == "yes":
    print("仍有使用者：sys-libs/binutils-libs-2.46.1 /usr/lib64/libbfd-2.46.0.so")
    print("    /usr/bin/something")
    sys.exit(1)
print("仍在登记但没有使用者：sys-libs/binutils-libs-2.46.1 /usr/lib64/libbfd-2.46.0.so")
sys.exit(0)
EOF2
    chmod +x "${d}/bin/emerge" "${d}/consumers"
    PATH="${d}/bin:${PATH}" CONSUMERS="${d}/consumers" \
        bash "${ROOT}/build/rebuild-preserved.sh" "${d}/log" > "${d}/out" 2>&1
    rc=$?
    printf '%s|%s|%s|%s|%s|%s\n' "${rc}" \
        "$(grep -c -- '--usepkg=n' "${d}/emerge.args" 2>/dev/null)" \
        "$(grep -c -- '--getbinpkg=n' "${d}/emerge.args" 2>/dev/null)" \
        "$(grep -c -- '--changed-use' "${d}/emerge.args" 2>/dev/null)" \
        "$(grep -c 'preserved-rebuild' "${d}/emerge.args" 2>/dev/null)" \
        "$(grep -c '没有使用者' "${d}/out" 2>/dev/null)"
    rm -rf "${d}"
}

log_probe() {
    local emerge_rc="$1" d rc
    d=$(mktemp -d)
    mkdir -p "${d}/bin"
    printf '#!/bin/bash\nexit %s\n' "${emerge_rc}" > "${d}/bin/emerge"
    printf '#!/usr/bin/env python3\nopen("%s/asked", "a").close()\n' "${d}" \
        > "${d}/consumers"
    chmod +x "${d}/bin/emerge" "${d}/consumers"
    PATH="${d}/bin:${PATH}" CONSUMERS="${d}/consumers" \
        bash "${ROOT}/build/rebuild-preserved.sh" "${d}/log" > /dev/null 2>&1
    printf '%s|%s\n' \
        "$(test -e "${d}/log" && echo kept || echo removed)" \
        "$(test -e "${d}/asked" && echo 1 || echo 0)"
    rm -rf "${d}"
}

echo "== 保留库的使用者必须从源码重建"

IFS='|' read -r rc no_usepkg no_getbinpkg changed_use called noted <<< "$(probe no)"
ok "没有使用者时退出码 0" "${rc}" "0"
ok "呼叫了 @preserved-rebuild" "${called}" "1"
ok "不重用本地二进位包" "${no_usepkg}" "1"
# FEATURES carries getbinpkg, so without this the rebuild fetches the very
# binary package that is linked against the library being replaced.
ok "不从 binhost 取二进位包" "${no_getbinpkg}" "1"
# --changed-use resolves this set to zero packages: a preserved library never
# changes anyone's USE, so the rebuild would silently do nothing.
ok "不带 --changed-use" "${changed_use}" "0"
ok "残留登记记进日志而不是挡下这一轮" "${noted}" "1"

IFS='|' read -r rc no_usepkg no_getbinpkg changed_use called noted <<< "$(probe yes)"
ok "真的有使用者时以非零退出" "${rc}" "1"

# The log goes on success and stays on failure. A rebuild that failed leaves
# a state the consumer question cannot be trusted on, so it is not asked.
IFS='|' read -r log_state consumers_called <<< "$(log_probe 0)"
ok "成功时不留下重建日志" "${log_state}" "removed"
IFS='|' read -r log_state consumers_called <<< "$(log_probe 2)"
ok "重建失败时保留日志" "${log_state}" "kept"
ok "重建失败后不再查使用者" "${consumers_called}" "0"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
