#!/bin/bash
# 全量构建：跑 packages.txt 里的每个包，产物暂存待发布。
#
# 基础镜像已就绪时不会再做 @world 对齐，那一步在 base-image.sh 里，按镜像
# 年龄触发。
#
# JOBS 比 base-image.sh 那边高：清单里的包彼此独立，能吃满并行；@world 对齐
# 那段是 perl 的依赖链，串行，给再多也用不上。

set -euo pipefail

cd "$(dirname "$0")/.."

exec env \
    SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}" \
    OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}" \
    TREE="${TREE:-/var/db/repos/gentoo}" \
    LIST="${LIST:-$(pwd)/build/packages.txt}" \
    JOBS="${JOBS:-24}" \
    MAKEOPTS="${MAKEOPTS:--j8}" \
    ./build/build-container.sh
