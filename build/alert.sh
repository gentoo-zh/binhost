# shellcheck shell=bash
# Post a line to Telegram. Sourced, not executed.
#
# Both machines need this and both used to carry their own copy. The copies
# drifted: two of the four call sites guarded the credentials and two did not,
# so on those two a half-written alert.conf took the script down at exactly the
# moment it had something to report.
#
#   . "$(dirname "$0")/alert.sh"
#   alert "something happened"
#
# Silence is deliberate when there are no credentials: a machine that was never
# given any should not fail its jobs over it.

alert() {
    local conf="${ALERT_CONF:-/etc/binhost/alert.conf}"

    # A file that exists but cannot be read is not the same as no file at all.
    # The first means the owner and the user running this disagree, and alerts
    # go nowhere with nothing to show for it.
    if [[ -e ${conf} && ! -r ${conf} ]]; then
        echo "!! ${conf} 读不到（当前用户 $(id -un)），告警发不出去" >&2
        return 0
    fi
    [[ -r ${conf} ]] || return 0

    # Read in a subshell so the credentials do not linger in the caller's
    # environment, and so a broken conf cannot redefine anything it uses.
    local token chat
    # shellcheck source=/dev/null
    token=$(. "${conf}" 2>/dev/null; printf '%s' "${TELEGRAM_TOKEN:-}")
    # shellcheck source=/dev/null
    chat=$(. "${conf}" 2>/dev/null; printf '%s' "${TELEGRAM_CHAT:-}")

    # Under set -u a missing variable would take down the caller. That is the
    # opposite of what alerting is for, so treat an incomplete conf as no conf.
    if [[ -z ${token} || -z ${chat} ]]; then
        echo "!! ${conf} 缺 TELEGRAM_TOKEN 或 TELEGRAM_CHAT，告警发不出去" >&2
        return 0
    fi

    curl -fsS --max-time 20 -o /dev/null \
        "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=$1" || true
}
