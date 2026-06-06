#!/bin/bash
# Mark successful boot and trigger rollback when repeated boots fail after OTA.
#
# U-Boot variables used:
#   mmcbootpart / mmcrootpart - active rootfs partition (1 or 2)
#   ota_boot_tries            - failed boot counter
#   ota_boot_ok               - 1 when last boot was confirmed healthy

set -euo pipefail

MAX_BOOT_TRIES=3
STATE_DIR="/home/root/.ne/ota"
MARKER="${STATE_DIR}/boot_success"

log() {
    logger -t ota-boot-health "$*"
}

get_env() {
    fw_printenv -n "$1" 2>/dev/null || true
}

set_env() {
    fw_setenv "$1" "$2"
}

current_part() {
    get_env mmcrootpart
}

rollback_part() {
    local active
    active="$(current_part)"
    if [ "$active" = "1" ]; then
        echo 2
    else
        echo 1
    fi
}

if [ ! -x /usr/bin/fw_printenv ] || [ ! -x /usr/bin/fw_setenv ]; then
    log "fw_utils not available, skipping boot health check"
    exit 0
fi

mkdir -p "$STATE_DIR"

boot_tries="$(get_env ota_boot_tries)"
boot_tries="${boot_tries:-0}"

if [ -f "$MARKER" ]; then
  # Previous boot completed health window; clear tries and mark OK.
  set_env ota_boot_ok 1
  set_env ota_boot_tries 0
  rm -f "$MARKER"
  log "Boot confirmed healthy on partition $(current_part)"
  exit 0
fi

# First stage after switch: increment tries until health marker is written.
boot_tries=$((boot_tries + 1))
set_env ota_boot_tries "$boot_tries"
set_env ota_boot_ok 0
log "Boot attempt ${boot_tries}/${MAX_BOOT_TRIES} on partition $(current_part)"

if [ "$boot_tries" -ge "$MAX_BOOT_TRIES" ]; then
    rollback="$(rollback_part)"
    log "Boot failed ${MAX_BOOT_TRIES} times, rolling back to partition ${rollback}"
    set_env mmcbootpart "$rollback"
    set_env mmcrootpart "$rollback"
    set_env ota_boot_tries 0
    set_env ota_boot_ok 0
    sync
    reboot
fi

# Defer success marker: systemd timer writes it after services are up.
exit 0
