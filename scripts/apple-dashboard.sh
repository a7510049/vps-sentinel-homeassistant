#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/vps-monitor.env"
readonly HA_DIR="/opt/homeassistant"
readonly HA_CONFIG="${HA_DIR}/config/configuration.yaml"
readonly DASHBOARD_FILE="${HA_DIR}/config/vps-sentinel-dashboard.yaml"
readonly CARD_SOURCE="/opt/vps-monitor/vps-sentinel-apple-card.js"
readonly CARD_TARGET="${HA_DIR}/config/www/vps-sentinel-apple-card.js"
readonly VERSION_FILE="/opt/vps-monitor/.version"

if [[ ${EUID} -ne 0 ]]; then
  echo "[錯誤] 請使用 sudo：sudo vps-sentinel-apple" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" || ! -f "${HA_CONFIG}" ||
      ! -f "${CARD_SOURCE}" ]]; then
  echo "[錯誤] Apple 風格面板元件尚未完整安裝。" >&2
  exit 1
fi

read_env() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

installed_version() {
  local version
  version="$(tr -d '[:space:]' < "${VERSION_FILE}" 2>/dev/null || true)"
  if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    version="$(sed -n 's/^const CARD_VERSION = "\([^"]*\)";.*/\1/p' \
      "${CARD_SOURCE}" | head -n 1)"
  fi
  if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    version="development"
  fi
  printf '%s' "${version}"
}

resource_url() {
  printf '/local/vps-sentinel-apple-card.js?v=%s' "$(installed_version)"
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
  local changed=false
  install -d -m 0755 "$(dirname "${CARD_TARGET}")"
  if [[ ! -f "${CARD_TARGET}" ]] ||
     ! cmp -s "${CARD_SOURCE}" "${CARD_TARGET}"; then
    install -m 0644 "${CARD_SOURCE}" "${CARD_TARGET}"
    changed=true
  fi
  if [[ "${changed}" == "true" ]]; then
    echo "[完成] Apple 風格面板元件已同步。"
    echo "[提示] 前端檔案更新不需要重新啟動 Home Assistant。"
  else
    echo "[完成] Apple 風格面板元件已是最新版本。"
  fi
}

show_resource_steps() {
  local url
  url="$(resource_url)"
  cat <<EOF

首次使用請在 Home Assistant 新增一筆儀表板資源；
更新既有版本時，請確認包含 Apple 卡片的資源只有一筆：
  網址：${url}
  類型：JavaScript 模組

首次使用完成資源註冊後執行：
  sudo vps-sentinel apple --apply

更新既有版本時，請把原本資源網址的版本參數改成上方網址，
再重新整理 Home Assistant App；不需要重新啟動 Home Assistant。
程式不會直接修改 .storage。
EOF
}

remove_legacy_auto_module() {
  local backup temporary
  if ! grep -Eq '^[[:space:]]+- /local/vps-sentinel-apple-card\.js' \
      "${HA_CONFIG}"; then
    return
  fi

  backup="$(mktemp)"
  temporary="$(mktemp)"
  cp -a "${HA_CONFIG}" "${backup}"
  awk '
    /^  extra_module_url:[[:space:]]*$/ {
      in_modules=1
      key=$0
      key_printed=0
      next
    }
    in_modules && /^    - / {
      if ($0 !~ /\/local\/vps-sentinel-apple-card\.js/) {
        if (!key_printed) {
          print key
          key_printed=1
        }
        print
      }
      next
    }
    in_modules {
      in_modules=0
    }
    { print }
  ' "${HA_CONFIG}" > "${temporary}"
  install -m 0644 "${temporary}" "${HA_CONFIG}"

  if ! docker exec homeassistant python -m homeassistant \
      --script check_config --config /config; then
    install -m 0644 "${backup}" "${HA_CONFIG}"
    rm -f -- "${backup}" "${temporary}"
    echo "[錯誤] 舊版自動載入設定清理失敗，已回復原設定。" >&2
    exit 1
  fi
  rm -f -- "${backup}" "${temporary}"
  echo "[完成] 已移除 RC3 的自動載入設定。"
}

apply_dashboard() {
  local vps_id backup had_dashboard=false
  vps_id="$(yaml_id "$(read_env VPS_ID)")"
  if [[ -z "${vps_id}" ]]; then
    echo "[錯誤] VPS_ID 無效，無法建立面板。" >&2
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
        country: sensor.${vps_id}_country_code
        provider: sensor.${vps_id}_provider
        osName: sensor.${vps_id}_os_name
        maintenance: sensor.${vps_id}_maintenance_status
        maintenanceEvent: event.${vps_id}_maintenance_event
        commandTopic: vps/$(read_env VPS_ID)/command
YAML

  if ! docker exec homeassistant python -m homeassistant \
      --script check_config --config /config; then
    if [[ "${had_dashboard}" == "true" ]]; then
      cp -a "${backup}" "${DASHBOARD_FILE}"
    else
      rm -f -- "${DASHBOARD_FILE}"
    fi
    [[ "${had_dashboard}" != "true" ]] || rm -f -- "${backup}"
    echo "[錯誤] Home Assistant 驗證失敗，已回復原面板。" >&2
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
    echo "[錯誤] Home Assistant 啟動失敗，已回復原面板。" >&2
    exit 1
  fi
  [[ "${had_dashboard}" != "true" ]] || rm -f -- "${backup}"
  echo "[完成] Apple 風格面板已套用。"
  echo "若要恢復原生面板：sudo vps-sentinel dashboard"
}

remove_legacy_auto_module
install_asset
case "${1:-}" in
  --apply) apply_dashboard ;;
  "") show_resource_steps ;;
  *)
    echo "[錯誤] 未知參數：${1}" >&2
    echo "用法：sudo vps-sentinel apple [--apply]" >&2
    exit 2
    ;;
esac
