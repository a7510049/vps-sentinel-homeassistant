#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/vps-monitor.env"
readonly HA_DIR="/opt/homeassistant"
readonly HA_CONFIG="${HA_DIR}/config/configuration.yaml"
readonly DASHBOARD_FILE="${HA_DIR}/config/vps-sentinel-dashboard.yaml"
readonly CARD_SOURCE="/opt/vps-monitor/vps-sentinel-apple-card.js"
readonly CARD_TARGET="${HA_DIR}/config/www/vps-sentinel-apple-card.js"
readonly RESOURCE_URL="/local/vps-sentinel-apple-card.js?v=0.8.0-rc.3"

if [[ ${EUID} -ne 0 ]]; then
  echo "❌ 請使用 sudo：sudo vps-sentinel-apple" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" || ! -f "${HA_CONFIG}" ||
      ! -f "${CARD_SOURCE}" ]]; then
  echo "❌ Apple 面板元件尚未完整安裝。" >&2
  exit 1
fi

read_env() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

yaml_id() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9_]/_/g'
}

wait_for_home_assistant() {
  local _
  for _ in {1..40}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8123/ \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

install_asset() {
  local changed=false card_backup=""
  install -d -m 0755 "$(dirname "${CARD_TARGET}")"
  if [[ ! -f "${CARD_TARGET}" ]] ||
     ! cmp -s "${CARD_SOURCE}" "${CARD_TARGET}"; then
    if [[ -f "${CARD_TARGET}" ]]; then
      card_backup="$(mktemp)"
      cp -a "${CARD_TARGET}" "${card_backup}"
    fi
    install -m 0644 "${CARD_SOURCE}" "${CARD_TARGET}"
    changed=true
  fi
  if [[ "${changed}" == "true" ]]; then
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    )
    if ! wait_for_home_assistant; then
      if [[ -n "${card_backup}" ]]; then
        install -m 0644 "${card_backup}" "${CARD_TARGET}"
      else
        rm -f -- "${CARD_TARGET}"
      fi
      (
        cd "${HA_DIR}"
        docker compose restart homeassistant
      ) || true
      echo "❌ Home Assistant 未能在預期時間內恢復。" >&2
      exit 1
    fi
    [[ -z "${card_backup}" ]] || rm -f -- "${card_backup}"
    echo "✅ Apple 面板元件已安裝。"
  else
    echo "✅ Apple 面板元件已是最新版本。"
  fi
}

show_resource_steps() {
  echo "✅ Apple 面板元件已由 Home Assistant 自動載入。"
  echo "程式使用官方 frontend.extra_module_url，不會修改 .storage。"
}

register_frontend_module() {
  local backup temporary changed=false
  if grep -Fq -- "${RESOURCE_URL}" "${HA_CONFIG}"; then
    show_resource_steps
    return
  fi

  backup="$(mktemp)"
  temporary="$(mktemp)"
  cp -a "${HA_CONFIG}" "${backup}"

  if grep -Eq '^[[:space:]]+- /local/vps-sentinel-apple-card\.js' \
      "${HA_CONFIG}"; then
    awk -v url="${RESOURCE_URL}" '
      /^[[:space:]]+- \/local\/vps-sentinel-apple-card\.js/ && !done {
        print "    - " url
        done=1
        next
      }
      { print }
    ' "${HA_CONFIG}" > "${temporary}"
  elif grep -Eq '^  extra_module_url:[[:space:]]*$' "${HA_CONFIG}"; then
    awk -v url="${RESOURCE_URL}" '
      !done && /^  extra_module_url:[[:space:]]*$/ {
        print
        print "    - " url
        done=1
        next
      }
      { print }
    ' "${HA_CONFIG}" > "${temporary}"
  elif grep -Eq '^frontend:[[:space:]]*$' "${HA_CONFIG}"; then
    awk -v url="${RESOURCE_URL}" '
      !done && /^frontend:[[:space:]]*$/ {
        print
        print "  extra_module_url:"
        print "    - " url
        done=1
        next
      }
      { print }
    ' "${HA_CONFIG}" > "${temporary}"
  else
    cp -a "${HA_CONFIG}" "${temporary}"
    printf '\nfrontend:\n  extra_module_url:\n    - %s\n' \
      "${RESOURCE_URL}" >> "${temporary}"
  fi
  install -m 0644 "${temporary}" "${HA_CONFIG}"
  changed=true

  if ! docker exec homeassistant python -m homeassistant \
      --script check_config --config /config; then
    install -m 0644 "${backup}" "${HA_CONFIG}"
    rm -f -- "${backup}" "${temporary}"
    echo "❌ 自動載入設定驗證失敗，已回復原設定。" >&2
    exit 1
  fi
  if [[ "${changed}" == "true" ]]; then
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    )
    if ! wait_for_home_assistant; then
      install -m 0644 "${backup}" "${HA_CONFIG}"
      (
        cd "${HA_DIR}"
        docker compose restart homeassistant
      ) || true
      rm -f -- "${backup}" "${temporary}"
      echo "❌ 自動載入設定啟用失敗，已回復原設定。" >&2
      exit 1
    fi
  fi
  rm -f -- "${backup}" "${temporary}"
  show_resource_steps
}

apply_dashboard() {
  local vps_id backup had_dashboard=false
  vps_id="$(yaml_id "$(read_env VPS_ID)")"
  if [[ -z "${vps_id}" ]]; then
    echo "❌ VPS_ID 無效，無法建立面板。" >&2
    exit 1
  fi
  backup="${DASHBOARD_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
  if [[ -f "${DASHBOARD_FILE}" ]]; then
    cp -a "${DASHBOARD_FILE}" "${backup}"
    had_dashboard=true
  fi

  cat > "${DASHBOARD_FILE}" <<YAML
title: VPS Sentinel
views:
  - title: 主機狀態
    path: overview
    icon: mdi:server
    cards:
      - type: custom:vps-sentinel-apple-card
        title: 主機狀態
        cpu: sensor.${vps_id}_cpu_percent
        memory: sensor.${vps_id}_memory_percent
        disk: sensor.${vps_id}_disk_percent
        health: sensor.${vps_id}_health_status
        reporting: binary_sensor.${vps_id}_reporting
        uptime: sensor.${vps_id}_uptime_hours
        updates: sensor.${vps_id}_security_updates
        containers: sensor.${vps_id}_docker_running
        bootTime: sensor.${vps_id}_boot_time
        serviceProblem: binary_sensor.${vps_id}_service_problem
        rebootRequired: binary_sensor.${vps_id}_reboot_required
YAML

  if ! docker exec homeassistant python -m homeassistant \
      --script check_config --config /config; then
    if [[ "${had_dashboard}" == "true" ]]; then
      cp -a "${backup}" "${DASHBOARD_FILE}"
    else
      rm -f -- "${DASHBOARD_FILE}"
    fi
    [[ "${had_dashboard}" != "true" ]] || rm -f -- "${backup}"
    echo "❌ Home Assistant 驗證失敗，已回復原面板。" >&2
    exit 1
  fi

  if ! (
    cd "${HA_DIR}"
    docker compose restart homeassistant
  ) || ! wait_for_home_assistant; then
    if [[ "${had_dashboard}" == "true" ]]; then
      cp -a "${backup}" "${DASHBOARD_FILE}"
    else
      rm -f -- "${DASHBOARD_FILE}"
    fi
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    ) || true
    [[ "${had_dashboard}" != "true" ]] || rm -f -- "${backup}"
    echo "❌ Home Assistant 啟動失敗，已回復原面板。" >&2
    exit 1
  fi
  [[ "${had_dashboard}" != "true" ]] || rm -f -- "${backup}"
  echo "✅ Apple 風格面板已套用。"
  echo "若要恢復原生面板：sudo vps-sentinel dashboard"
}

install_asset
register_frontend_module
apply_dashboard
