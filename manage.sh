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
readonly VERSION_FILE="/opt/vps-monitor/.version"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  readonly C_RESET=$'\033[0m'
  readonly C_CYAN=$'\033[1;36m'
  readonly C_GREEN=$'\033[1;32m'
  readonly C_YELLOW=$'\033[1;33m'
  readonly C_RED=$'\033[1;31m'
  readonly C_PURPLE=$'\033[1;35m'
else
  readonly C_RESET="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED="" C_PURPLE=""
fi

green()  { printf '%s✅ %s%s\n' "${C_GREEN}" "$*" "${C_RESET}"; }
yellow() { printf '%s⚠️  %s%s\n' "${C_YELLOW}" "$*" "${C_RESET}"; }
red()    { printf '%s❌ %s%s\n' "${C_RED}" "$*" "${C_RESET}" >&2; }
heading(){ printf '\n%s%s%s\n' "${C_CYAN}" "$*" "${C_RESET}"; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel"
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
      yellow "${service}：未運作或未安裝"
    fi
  done
  if command -v docker >/dev/null 2>&1 &&
     docker ps --format '{{.Names}}' 2>/dev/null |
       grep -qx homeassistant; then
    green "homeassistant：正常"
  else
    yellow "homeassistant：未運作或未安裝"
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

service_state() {
  local service="$1"
  if systemctl is-active --quiet "${service}" 2>/dev/null; then
    printf '正常'
  else
    printf '需檢查'
  fi
}

show_header() {
  local version
  version="$(cat "${VERSION_FILE}" 2>/dev/null || printf '開發版')"
  clear
  printf '%s' "${C_PURPLE}"
  cat <<'BANNER'
╭────────────────────────────────────────╮
│  🖥️  VPS Sentinel                     │
│  輕量、安心的 VPS 狀態監控             │
╰────────────────────────────────────────╯
BANNER
  printf '%s' "${C_RESET}"
  printf '  版本 %-10s  監控 %-8s  MQTT %s\n' \
    "${version}" "$(service_state vps-monitor)" "$(service_state mosquitto)"
  echo
}

pause_menu() {
  [[ -t 0 ]] || return 0
  echo
  read -r -p "按 Enter 返回……" _
}

run_tool() {
  local label="$1" command="$2"
  if [[ ! -x "${command}" ]]; then
    yellow "找不到${label}，請先執行 VPS Sentinel 更新。"
    return 1
  fi
  if ! "${command}"; then
    red "${label}未完成，請查看上方訊息。"
    return 1
  fi
}

show_settings() {
  heading "目前監控設定"
  if [[ ! -f "${ENV_FILE}" ]]; then
    yellow "找不到 ${ENV_FILE}"
    return
  fi
  echo "VPS 名稱：$(read_env VPS_NAME 未設定)"
  echo "資源更新：$(read_env PUBLISH_INTERVAL 15) 秒"
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
  echo "  1) 極省資源：每 60 秒更新資源"
  echo "  2) 平衡模式：每 15 秒更新資源（推薦）"
  echo "  3) 即時監控：每 10 秒更新資源"
  read -r -p "請選擇 [2]：" choice
  choice="${choice:-2}"
  backup="${ENV_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -a "${ENV_FILE}" "${backup}"
  case "${choice}" in
    1)
      set_env PUBLISH_INTERVAL 60
      set_env HEALTH_CHECK_INTERVAL 900
      set_env UPDATE_CHECK_INTERVAL 86400
      set_env MONITOR_NETWORK false
      set_env OVERLOAD_SAMPLES 5
      ;;
    2)
      set_env PUBLISH_INTERVAL 15
      set_env HEALTH_CHECK_INTERVAL 300
      set_env UPDATE_CHECK_INTERVAL 86400
      set_env MONITOR_NETWORK false
      set_env OVERLOAD_SAMPLES 20
      ;;
    3)
      set_env PUBLISH_INTERVAL 10
      set_env HEALTH_CHECK_INTERVAL 60
      set_env UPDATE_CHECK_INTERVAL 21600
      set_env MONITOR_NETWORK true
      set_env OVERLOAD_SAMPLES 30
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
  - title: 主機狀態
    path: overview
    icon: mdi:server
    cards:
      - type: conditional
        conditions:
          - condition: state
            entity: sensor.${vps_id}_health_status
            state_not: 運作正常
        card:
          type: tile
          entity: sensor.${vps_id}_health_status
          name: 主機需要留意
          color: orange
      - type: markdown
        content: |
          ## 🖥️ 主機資源
      - type: horizontal-stack
        cards:
          - type: gauge
            entity: sensor.${vps_id}_memory_percent
            name: 記憶體
            min: 0
            max: 100
            severity:
              green: 0
              yellow: 75
              red: 90
          - type: gauge
            entity: sensor.${vps_id}_disk_percent
            name: 磁碟
            min: 0
            max: 100
            severity:
              green: 0
              yellow: 70
              red: 85
      - type: markdown
        content: >-
          記憶體已使用
          **{{ state_attr('sensor.${vps_id}_memory_percent', 'used_gb') }} GB**
          ／ {{ state_attr('sensor.${vps_id}_memory_percent', 'total_gb') }} GB
          · 磁碟剩餘
          **{{ state_attr('sensor.${vps_id}_disk_percent', 'free_gb') }} GB**
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: sensor.${vps_id}_cpu_percent
            name: CPU
            color: blue
          - type: tile
            entity: sensor.${vps_id}_uptime_hours
            name: 已運作
            color: blue
      - type: markdown
        content: |
          ## 🛡️ 運作狀態
      - type: grid
        columns: 2
        square: false
        cards:
          - type: tile
            entity: sensor.${vps_id}_health_status
            name: 整體狀態
          - type: tile
            entity: binary_sensor.${vps_id}_reporting
            name: 資料更新
          - type: tile
            entity: sensor.${vps_id}_security_updates
            name: 安全更新
          - type: tile
            entity: sensor.${vps_id}_docker_running
            name: 運作中容器
          - type: tile
            entity: binary_sensor.${vps_id}_service_problem
            name: 服務狀態
          - type: tile
            entity: binary_sensor.${vps_id}_reboot_required
            name: 重新啟動
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

settings_menu() {
  local choice
  while true; do
    show_header
    heading "⚙️  監控設定"
    echo "  1. 查看目前設定"
    echo "  2. 切換資源模式"
    echo "  3. 調整告警門檻"
    echo "  0. 返回主選單"
    echo
    read -r -p "請選擇 [0]：" choice
    case "${choice:-0}" in
      1) show_settings; pause_menu ;;
      2) change_profile; pause_menu ;;
      3) change_thresholds; pause_menu ;;
      0) return ;;
      *) yellow "請輸入 0 到 3。"; pause_menu ;;
    esac
  done
}

home_assistant_menu() {
  local choice
  while true; do
    show_header
    heading "🏠 Home Assistant"
    echo "  1. 建立或更新監控面板"
    echo "  2. 管理通知與自動化模板"
    echo "  3. 安全更新 Home Assistant"
    echo "  0. 返回主選單"
    echo
    read -r -p "請選擇 [0]：" choice
    case "${choice:-0}" in
      1) install_dashboard; pause_menu ;;
      2) run_tool "自動化模板工具" "${AUTOMATIONS_COMMAND}" || true; pause_menu ;;
      3) run_tool "Home Assistant 更新" "${UPDATE_COMMAND}" || true; pause_menu ;;
      0) return ;;
      *) yellow "請輸入 0 到 3。"; pause_menu ;;
    esac
  done
}

maintenance_menu() {
  local choice
  while true; do
    show_header
    heading "🧰 系統維護"
    echo "  1. 執行健康檢查與修復"
    echo "  2. 備份與還原"
    echo "  3. 更新 VPS Sentinel"
    echo "  4. 完整移除"
    echo "  0. 返回主選單"
    echo
    read -r -p "請選擇 [0]：" choice
    case "${choice:-0}" in
      1) run_tool "健康檢查" "${DOCTOR_COMMAND}" || true; pause_menu ;;
      2) run_tool "備份管理" "${BACKUP_COMMAND}" || true; pause_menu ;;
      3) run_tool "VPS Sentinel 更新" "${UPGRADE_COMMAND}" || true; pause_menu ;;
      4)
        yellow "下一步會進入移除工具，實際刪除前仍會再次確認。"
        run_tool "移除工具" "${UNINSTALL_COMMAND}" || true
        pause_menu
        ;;
      0) return ;;
      *) yellow "請輸入 0 到 4。"; pause_menu ;;
    esac
  done
}

print_help() {
  cat <<'HELP'
用法：sudo vps-sentinel [指令]

未指定指令時開啟中文維護中心。

指令：
  status       查看服務狀態
  settings     查看目前監控設定
  dashboard    建立或更新 Home Assistant 監控面板
  doctor       執行健康檢查
  backup       開啟備份與還原工具
  upgrade      更新 VPS Sentinel
  ha-update    更新 Home Assistant
  help         顯示這份說明
HELP
}

run_command() {
  case "${1}" in
    status) show_status ;;
    settings) show_settings ;;
    dashboard) install_dashboard ;;
    doctor) run_tool "健康檢查" "${DOCTOR_COMMAND}" ;;
    backup) run_tool "備份管理" "${BACKUP_COMMAND}" ;;
    upgrade) run_tool "VPS Sentinel 更新" "${UPGRADE_COMMAND}" ;;
    ha-update) run_tool "Home Assistant 更新" "${UPDATE_COMMAND}" ;;
    help|-h|--help) print_help ;;
    *)
      red "未知指令：${1}"
      print_help
      return 2
      ;;
  esac
}

main_menu() {
  local choice
  if [[ ! -t 0 ]]; then
    red "互動式維護中心需要終端機；自動化操作請使用 vps-sentinel help。"
    return 1
  fi
  while true; do
    show_header
    echo "請選擇要進行的操作："
    echo
    echo "  1. 📊 查看系統狀態"
    echo "  2. ⚙️  調整監控設定"
    echo "  3. 🏠 管理 Home Assistant"
    echo "  4. 🧰 系統維護"
    echo "  0. 離開"
    echo
    read -r -p "請選擇 [1]：" choice
    case "${choice:-1}" in
      1) show_status; pause_menu ;;
      2) settings_menu ;;
      3) home_assistant_menu ;;
      4) maintenance_menu ;;
      0)
        echo "已離開 VPS Sentinel。"
        return
        ;;
      *) yellow "請輸入 0 到 4。"; pause_menu ;;
    esac
  done
}

if (( $# > 0 )); then
  run_command "$1"
else
  main_menu
fi
