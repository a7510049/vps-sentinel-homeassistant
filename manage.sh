#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/vps-monitor.env"
readonly HA_DIR="/opt/homeassistant"
readonly HA_CONFIG="${HA_DIR}/config/configuration.yaml"
readonly DASHBOARD_FILE="${HA_DIR}/config/vps-sentinel-dashboard.yaml"
readonly UPDATE_COMMAND="/usr/local/sbin/vps-sentinel-update"
readonly UNINSTALL_COMMAND="/usr/local/sbin/vps-sentinel-uninstall"
readonly UPGRADE_COMMAND="/usr/local/sbin/vps-sentinel-upgrade"
readonly DOCTOR_COMMAND="/usr/local/sbin/vps-sentinel-doctor"
readonly BACKUP_COMMAND="/usr/local/sbin/vps-sentinel-backup"
readonly AUTOMATIONS_COMMAND="/usr/local/sbin/vps-sentinel-automations"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }
heading(){ printf '\n\033[1;36m%s\033[0m\n' "$*"; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "維護中心只能在互動式終端機執行。"
  exit 1
fi

read_env() {
  local key="$1" fallback="${2-}" value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" 2>/dev/null | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value:-${fallback}}"
}

env_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "${value}"
}

set_env() {
  local key="$1" value="$2" temporary
  temporary="$(mktemp)"
  awk -v key="${key}" -v value="$(env_quote "${value}")" '
    BEGIN { changed = 0 }
    $0 ~ "^" key "=" {
      if (!changed) print key "=" value
      changed = 1
      next
    }
    { print }
    END { if (!changed) print key "=" value }
  ' "${ENV_FILE}" > "${temporary}"
  install -m 0600 "${temporary}" "${ENV_FILE}"
  rm -f -- "${temporary}"
}

show_status() {
  local service state
  heading "服務狀態"
  for service in vps-monitor mosquitto docker; do
    if systemctl is-active --quiet "${service}" 2>/dev/null; then
      green "${service}：正常"
    else
      yellow "${service}：未運行或未安裝"
    fi
  done
  if command -v docker >/dev/null 2>&1 &&
     docker ps --format '{{.Names}}' 2>/dev/null |
       grep -qx homeassistant; then
    green "homeassistant：正常"
  else
    yellow "homeassistant：未運行或未安裝"
  fi
  if command -v tailscale >/dev/null 2>&1; then
    state="$(tailscale status --json 2>/dev/null |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["BackendState"])' \
      2>/dev/null || true)"
    if [[ "${state}" == "Running" ]]; then
      green "Tailscale：已連線"
    else
      yellow "Tailscale：${state:-無法讀取}"
    fi
  fi
}

show_settings() {
  heading "目前監控設定"
  if [[ ! -f "${ENV_FILE}" ]]; then
    yellow "找不到 ${ENV_FILE}"
    return
  fi
  echo "VPS 名稱：$(read_env VPS_NAME 未設定)"
  echo "回報間隔：$(read_env PUBLISH_INTERVAL 30) 秒"
  echo "服務檢查：$(read_env HEALTH_CHECK_INTERVAL 300) 秒"
  echo "CPU 告警：$(read_env CPU_WARN_PERCENT 90)%"
  echo "記憶體告警：$(read_env MEMORY_WARN_PERCENT 90)%"
  echo "磁碟告警：$(read_env DISK_WARN_PERCENT 85)%"
  echo "監控服務：$(read_env WATCH_SERVICES 無)"
  echo "網路速率：$(read_env MONITOR_NETWORK false)"
  echo "MQTT：$(read_env MQTT_HOST 未設定):$(read_env MQTT_PORT 1883)"
  echo "MQTT 密碼：已隱藏"
}

restart_monitor_or_rollback() {
  local backup="$1"
  if systemctl restart vps-monitor &&
     sleep 2 &&
     systemctl is-active --quiet vps-monitor; then
    green "新設定已套用，監控服務運作正常"
    return
  fi
  cp -a "${backup}" "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
  systemctl restart vps-monitor || true
  red "新設定無法啟動，已回復原設定。"
  journalctl -u vps-monitor -n 20 --no-pager || true
  return 1
}

change_profile() {
  local choice backup
  if [[ ! -f "${ENV_FILE}" ]]; then
    red "找不到監控設定，請先完成安裝。"
    return
  fi
  echo "  1) 極省資源：5 分鐘回報"
  echo "  2) 平衡模式：2 分鐘回報（推薦）"
  echo "  3) 即時監控：30 秒回報"
  read -r -p "請選擇 [2]：" choice
  choice="${choice:-2}"
  backup="${ENV_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -a "${ENV_FILE}" "${backup}"
  case "${choice}" in
    1)
      set_env PUBLISH_INTERVAL 300
      set_env HEALTH_CHECK_INTERVAL 900
      set_env UPDATE_CHECK_INTERVAL 86400
      set_env MONITOR_NETWORK false
      set_env OVERLOAD_SAMPLES 2
      ;;
    2)
      set_env PUBLISH_INTERVAL 120
      set_env HEALTH_CHECK_INTERVAL 300
      set_env UPDATE_CHECK_INTERVAL 86400
      set_env MONITOR_NETWORK false
      set_env OVERLOAD_SAMPLES 3
      ;;
    3)
      set_env PUBLISH_INTERVAL 30
      set_env HEALTH_CHECK_INTERVAL 60
      set_env UPDATE_CHECK_INTERVAL 21600
      set_env MONITOR_NETWORK true
      set_env OVERLOAD_SAMPLES 10
      ;;
    *)
      yellow "請選擇 1、2 或 3。"
      return
      ;;
  esac
  restart_monitor_or_rollback "${backup}"
}

valid_percent() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
    awk -v value="$1" 'BEGIN { exit !(value >= 1 && value <= 100) }'
}

change_thresholds() {
  local cpu memory disk backup
  if [[ ! -f "${ENV_FILE}" ]]; then
    red "找不到監控設定，請先完成安裝。"
    return
  fi
  read -r -p "CPU 告警門檻 [$(read_env CPU_WARN_PERCENT 90)]：" cpu
  cpu="${cpu:-$(read_env CPU_WARN_PERCENT 90)}"
  read -r -p "記憶體告警門檻 [$(read_env MEMORY_WARN_PERCENT 90)]：" memory
  memory="${memory:-$(read_env MEMORY_WARN_PERCENT 90)}"
  read -r -p "磁碟告警門檻 [$(read_env DISK_WARN_PERCENT 85)]：" disk
  disk="${disk:-$(read_env DISK_WARN_PERCENT 85)}"
  if ! valid_percent "${cpu}" ||
     ! valid_percent "${memory}" ||
     ! valid_percent "${disk}"; then
    red "門檻必須是 1 到 100 之間的數字。"
    return
  fi
  backup="${ENV_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -a "${ENV_FILE}" "${backup}"
  set_env CPU_WARN_PERCENT "${cpu}"
  set_env MEMORY_WARN_PERCENT "${memory}"
  set_env DISK_WARN_PERCENT "${disk}"
  restart_monitor_or_rollback "${backup}"
}

yaml_id() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9_]/_/g'
}

install_dashboard() {
  local vps_id config_backup dashboard_backup="" ready=false
  if [[ ! -f "${HA_CONFIG}" || ! -f "${ENV_FILE}" ]]; then
    red "找不到 Home Assistant 或 VPS Monitor 設定。"
    return
  fi
  vps_id="$(yaml_id "$(read_env VPS_ID)")"
  if [[ -z "${vps_id}" ]]; then
    red "VPS_ID 無效，無法建立儀表板。"
    return
  fi
  config_backup="${HA_CONFIG}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -a "${HA_CONFIG}" "${config_backup}"
  if [[ -e "${DASHBOARD_FILE}" ]]; then
    dashboard_backup="${DASHBOARD_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
    cp -a "${DASHBOARD_FILE}" "${dashboard_backup}"
  fi

  cat > "${DASHBOARD_FILE}" <<YAML
title: VPS Sentinel
views:
  - title: 系統資訊
    path: overview
    icon: mdi:server
    cards:
      - type: gauge
        entity: sensor.${vps_id}_cpu_percent
        name: CPU 使用率
        min: 0
        max: 100
        severity:
          green: 0
          yellow: 70
          red: 90
      - type: entities
        title: 🖥️ 主機資源
        show_header_toggle: false
        entities:
          - entity: sensor.${vps_id}_memory_percent
            name: 記憶體使用率
          - entity: sensor.${vps_id}_disk_percent
            name: 根目錄磁碟
          - entity: sensor.${vps_id}_uptime_hours
            name: 已運行時間
          - entity: sensor.${vps_id}_last_report
            name: 最近回報時間
          - entity: sensor.${vps_id}_security_updates
            name: 待安裝安全更新
          - entity: sensor.${vps_id}_docker_running
            name: 執行中的 Container
      - type: entities
        title: 🛡️ 健康狀態
        show_header_toggle: false
        entities:
          - entity: binary_sensor.${vps_id}_offline
            name: 連線狀態
          - entity: binary_sensor.${vps_id}_resource_overload
            name: 系統負載
          - entity: binary_sensor.${vps_id}_service_problem
            name: 服務運作
          - entity: binary_sensor.${vps_id}_reboot_required
            name: 重新啟動提醒
YAML

  if ! grep -q '^[[:space:]]*lovelace:' "${HA_CONFIG}"; then
    cat >> "${HA_CONFIG}" <<'YAML'

lovelace:
  mode: storage
  dashboards:
    vps-sentinel:
      mode: yaml
      title: VPS Sentinel
      icon: mdi:server
      show_in_sidebar: true
      filename: vps-sentinel-dashboard.yaml
YAML
  elif ! grep -q '^[[:space:]]*vps-sentinel:' "${HA_CONFIG}"; then
    cp -a "${config_backup}" "${HA_CONFIG}"
    red "偵測到既有 Lovelace 自訂設定，為避免覆蓋，未自動修改。"
    echo "儀表板草稿保留於 ${DASHBOARD_FILE}，可手動加入既有設定。"
    return
  fi

  if ! docker exec homeassistant python -m homeassistant \
      --script check_config --config /config; then
    cp -a "${config_backup}" "${HA_CONFIG}"
    if [[ -n "${dashboard_backup}" ]]; then
      cp -a "${dashboard_backup}" "${DASHBOARD_FILE}"
    else
      rm -f -- "${DASHBOARD_FILE}"
    fi
    red "Home Assistant 驗證失敗，已回復原設定。"
    return 1
  fi
  if ! (
    cd "${HA_DIR}"
    docker compose restart homeassistant
  ); then
    ready=false
  else
    for _ in {1..40}; do
      if curl -fsS --max-time 3 http://127.0.0.1:8123/ \
          >/dev/null 2>&1; then
        ready=true
        break
      fi
      sleep 3
    done
  fi
  if [[ "${ready}" != "true" ]]; then
    cp -a "${config_backup}" "${HA_CONFIG}"
    if [[ -n "${dashboard_backup}" ]]; then
      cp -a "${dashboard_backup}" "${DASHBOARD_FILE}"
    else
      rm -f -- "${DASHBOARD_FILE}"
    fi
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    ) || true
    red "Home Assistant 未能正常啟動，已回復原設定。"
    return 1
  fi
  green "VPS Sentinel 儀表板已加入側邊欄"
}

while true; do
  clear
  printf '\033[1;35m'
  cat <<'BANNER'
========================================================
 VPS Sentinel 維護中心
========================================================
BANNER
  printf '\033[0m'
  echo "  1) 查看服務狀態"
  echo "  2) 查看目前設定"
  echo "  3) 切換資源模式"
  echo "  4) 調整告警門檻"
  echo "  5) 建立或更新儀表板"
  echo "  6) Home Assistant 自動化模板"
  echo "  7) 一鍵健康檢查與修復"
  echo "  8) 備份與還原"
  echo "  9) 更新 VPS Sentinel"
  echo " 10) 安全更新 Home Assistant"
  echo " 11) 移除 VPS Sentinel"
  echo "  0) 離開"
  echo
  read -r -p "請選擇：" choice
  case "${choice}" in
    1) show_status ;;
    2) show_settings ;;
    3) change_profile ;;
    4) change_thresholds ;;
    5) install_dashboard ;;
    6)
      if [[ -x "${AUTOMATIONS_COMMAND}" ]]; then
        "${AUTOMATIONS_COMMAND}"
      else
        yellow "找不到自動化模板工具"
      fi
      ;;
    7)
      if [[ -x "${DOCTOR_COMMAND}" ]]; then
        "${DOCTOR_COMMAND}"
      else
        yellow "找不到健康檢查工具"
      fi
      ;;
    8)
      if [[ -x "${BACKUP_COMMAND}" ]]; then
        "${BACKUP_COMMAND}"
      else
        yellow "找不到備份管理工具"
      fi
      ;;
    9)
      if [[ -x "${UPGRADE_COMMAND}" ]]; then
        "${UPGRADE_COMMAND}"
      else
        yellow "找不到 VPS Sentinel 升級工具"
      fi
      ;;
    10)
      if [[ -x "${UPDATE_COMMAND}" ]]; then
        "${UPDATE_COMMAND}"
      else
        yellow "找不到 Home Assistant 更新工具"
      fi
      ;;
    11)
      if [[ -x "${UNINSTALL_COMMAND}" ]]; then
        "${UNINSTALL_COMMAND}"
      else
        yellow "找不到移除工具"
      fi
      ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 11。" ;;
  esac
  echo
  read -r -p "按 Enter 返回主選單……" _
done
