#!/usr/bin/env bash
set -Eeuo pipefail

readonly BACKUP_ROOT="/opt/vps-sentinel-backups"
readonly HA_DIR="/opt/homeassistant"
readonly ENV_FILE="/etc/vps-monitor.env"
readonly MONITOR_DIR="/opt/vps-monitor"
readonly SERVICE_FILE="/etc/systemd/system/vps-monitor.service"
readonly MQTT_CONF="/etc/mosquitto/conf.d/home-assistant.conf"
readonly MQTT_PASSWD="/etc/mosquitto/passwd"
readonly MQTT_ACL="/etc/mosquitto/vps-sentinel.acl"
readonly CONTROLLER_DATA="/var/lib/vps-sentinel-controller"
readonly CONTROLLER_ENV="/etc/vps-sentinel-controller.env"
readonly CONTROLLER_SERVICE="/etc/systemd/system/vps-sentinel-controller.service"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }
heading(){ printf '\n\033[1;36m%s\033[0m\n' "$*"; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel-backup"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "備份工具只能在互動式終端機執行。"
  exit 1
fi

install -d -m 0700 "${BACKUP_ROOT}"

read_env() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" 2>/dev/null | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

compose_path() {
  if [[ -f "${HA_DIR}/compose.yaml" ]]; then
    printf '%s' "${HA_DIR}/compose.yaml"
  elif [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    printf '%s' "${HA_DIR}/docker-compose.yml"
  fi
}

mqtt_probe() {
  local host port username password vps_id
  host="$(read_env MQTT_HOST)"
  port="$(read_env MQTT_PORT)"
  username="$(read_env MQTT_USERNAME)"
  password="$(read_env MQTT_PASSWORD)"
  vps_id="$(read_env VPS_ID)"
  [[ -n "${host}" && -n "${username}" && -n "${vps_id}" ]] || return 1
  timeout 12 mosquitto_sub \
    -h "${host}" -p "${port:-1883}" \
    -u "${username}" -P "${password}" \
    -t "vps/${vps_id}/online" -C 1 2>/dev/null |
    grep -qx 'ON'
}

wait_for_home_assistant() {
  local _
  for _ in {1..60}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8123/ \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

apply_staging() {
  local source="$1"
  if [[ -d "${source}/homeassistant/config" ]]; then
    rm -rf -- "${HA_DIR}/config"
    install -d -m 0755 "${HA_DIR}/config"
    cp -a "${source}/homeassistant/config/." "${HA_DIR}/config/"
  elif [[ -d "${source}/homeassistant" ]]; then
    # 相容 0.9.7 以前把設定直接放在 homeassistant/ 的備份。
    rm -rf -- "${HA_DIR}/config"
    install -d -m 0755 "${HA_DIR}/config"
    tar -C "${source}/homeassistant" \
      --exclude='compose.yaml' --exclude='docker-compose.yml' \
      -cf - . | tar -C "${HA_DIR}/config" -xf -
  fi

  if [[ -f "${source}/homeassistant/compose.yaml" ]]; then
    install -m 0644 "${source}/homeassistant/compose.yaml" \
      "${HA_DIR}/compose.yaml"
  elif [[ -f "${source}/homeassistant/docker-compose.yml" ]]; then
    install -m 0644 "${source}/homeassistant/docker-compose.yml" \
      "${HA_DIR}/compose.yaml"
  fi

  if [[ -f "${source}/monitor/vps-monitor.env" ]]; then
    install -m 0600 "${source}/monitor/vps-monitor.env" "${ENV_FILE}"
  fi
  if [[ -f "${source}/monitor/vps-monitor.service" ]]; then
    install -m 0644 "${source}/monitor/vps-monitor.service" "${SERVICE_FILE}"
  fi
  if [[ -f "${source}/mosquitto/home-assistant.conf" ]]; then
    install -d -m 0755 /etc/mosquitto/conf.d
    install -m 0644 "${source}/mosquitto/home-assistant.conf" "${MQTT_CONF}"
  fi
  if [[ -f "${source}/mosquitto/passwd" ]]; then
    install -m 0640 "${source}/mosquitto/passwd" "${MQTT_PASSWD}"
    chown root:mosquitto "${MQTT_PASSWD}"
  fi
  if [[ -f "${source}/mosquitto/vps-sentinel.acl" ]]; then
    install -m 0640 "${source}/mosquitto/vps-sentinel.acl" "${MQTT_ACL}"
    chown root:mosquitto "${MQTT_ACL}"
  fi
  if [[ -f "${source}/controller/vps-sentinel-controller.env" ]]; then
    install -m 0600 "${source}/controller/vps-sentinel-controller.env" \
      "${CONTROLLER_ENV}"
  fi
  if [[ -f "${source}/controller/vps-sentinel-controller.service" ]]; then
    install -m 0644 "${source}/controller/vps-sentinel-controller.service" \
      "${CONTROLLER_SERVICE}"
  fi
  if [[ -f "${source}/controller/enrollments.json" ]]; then
    install -d -m 0700 -o vps-sentinel-controller \
      -g vps-sentinel-controller "${CONTROLLER_DATA}"
    install -m 0600 -o vps-sentinel-controller \
      -g vps-sentinel-controller \
      "${source}/controller/enrollments.json" \
      "${CONTROLLER_DATA}/enrollments.json"
  fi
}

start_and_validate() {
  local compose
  systemctl daemon-reload
  systemctl restart mosquitto
  compose="$(compose_path)"
  [[ -n "${compose}" ]] || return 1
  (cd "${HA_DIR}" && docker compose up -d homeassistant)
  systemctl is-active --quiet mosquitto || return 1
  if [[ -f "${CONTROLLER_ENV}" ]]; then
    systemctl restart vps-sentinel-controller
    systemctl is-active --quiet vps-sentinel-controller || return 1
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    systemctl restart vps-monitor
    systemctl is-active --quiet vps-monitor || return 1
    mqtt_probe || return 1
  fi
  wait_for_home_assistant || return 1
  docker exec homeassistant python -m homeassistant \
    --script check_config --config /config >/dev/null 2>&1
}

list_backups() {
  heading "設定備份"
  if ! find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
      -print -quit | grep -q .; then
    yellow "目前沒有手動設定備份"
    return
  fi
  find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
    -printf '%TY-%Tm-%Td %TH:%TM  %10s bytes  %f\n' | sort -r
}

create_backup() {
  local timestamp staging archive compose
  timestamp="$(date +%Y%m%d-%H%M%S)"
  staging="$(mktemp -d)"
  archive="${BACKUP_ROOT}/settings-${timestamp}.tar.gz"
  trap 'rm -rf -- "${staging}"' RETURN

  install -d -m 0700 "${staging}/homeassistant/config" \
    "${staging}/monitor" "${staging}/mosquitto" \
    "${staging}/controller"
  compose="$(compose_path)"
  if [[ -n "${compose}" ]]; then
    cp -a "${compose}" "${staging}/homeassistant/compose.yaml"
  fi
  if [[ -d "${HA_DIR}/config" ]]; then
    tar -C "${HA_DIR}/config" \
      --exclude='home-assistant_v2.db*' \
      --exclude='home-assistant.log*' \
      --exclude='*.log' \
      --exclude='tts' \
      -cf - . | tar -C "${staging}/homeassistant/config" -xf -
  fi
  [[ ! -f "${ENV_FILE}" ]] ||
    install -m 0600 "${ENV_FILE}" "${staging}/monitor/vps-monitor.env"
  [[ ! -f "${SERVICE_FILE}" ]] ||
    cp -a "${SERVICE_FILE}" "${staging}/monitor/vps-monitor.service"
  [[ ! -f "${MONITOR_DIR}/.version" ]] ||
    cp -a "${MONITOR_DIR}/.version" "${staging}/monitor/.version"
  [[ ! -f "${MQTT_CONF}" ]] ||
    cp -a "${MQTT_CONF}" "${staging}/mosquitto/home-assistant.conf"
  [[ ! -f "${MQTT_PASSWD}" ]] ||
    cp -a "${MQTT_PASSWD}" "${staging}/mosquitto/passwd"
  [[ ! -f "${MQTT_ACL}" ]] ||
    cp -a "${MQTT_ACL}" "${staging}/mosquitto/vps-sentinel.acl"
  [[ ! -f "${CONTROLLER_ENV}" ]] ||
    install -m 0600 "${CONTROLLER_ENV}" \
      "${staging}/controller/vps-sentinel-controller.env"
  [[ ! -f "${CONTROLLER_SERVICE}" ]] ||
    cp -a "${CONTROLLER_SERVICE}" \
      "${staging}/controller/vps-sentinel-controller.service"
  [[ ! -f "${CONTROLLER_DATA}/enrollments.json" ]] ||
    install -m 0600 "${CONTROLLER_DATA}/enrollments.json" \
      "${staging}/controller/enrollments.json"
  {
    echo "format=3"
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "kind=settings"
    echo "compose=compose.yaml"
    echo "includes_mqtt=true"
  } > "${staging}/MANIFEST"
  tar -C "${staging}" -czf "${archive}" .
  chmod 0600 "${archive}"
  rm -rf -- "${staging}"
  trap - RETURN
  green "設定備份已建立：${archive}"
  echo "已包含 Home Assistant、Agent、Controller、節點名冊與完整 Broker policy。"
  echo "為節省空間，歷史資料庫與日誌不包含在此備份中。"
}

restore_backup() {
  local -a archives=()
  local choice archive staging safety recovery
  mapfile -t archives < <(
    find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
      -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-
  )
  if (( ${#archives[@]} == 0 )); then
    yellow "目前沒有可以還原的設定備份"
    return
  fi
  heading "選擇備份"
  for index in "${!archives[@]}"; do
    printf '  %d. %s\n' "$((index + 1))" "$(basename "${archives[index]}")"
  done
  echo "  0. 取消並返回"
  read -r -p "請選擇 [0]：" choice
  choice="${choice:-0}"
  [[ "${choice}" =~ ^[0-9]+$ ]] || {
    yellow "請輸入清單中的數字。"
    return
  }
  (( choice > 0 && choice <= ${#archives[@]} )) || return
  archive="${archives[choice - 1]}"
  case "${archive}" in
    "${BACKUP_ROOT}/"*.tar.gz) ;;
    *) red "備份路徑無效"; return 1 ;;
  esac
  if ! tar -tzf "${archive}" >/dev/null 2>&1; then
    red "備份檔損壞，已取消還原。"
    return 1
  fi
  staging="$(mktemp -d)"
  tar -xzf "${archive}" -C "${staging}"
  if [[ ! -f "${staging}/MANIFEST" ]] ||
     ! grep -Eq '^format=(1|2|3)$' "${staging}/MANIFEST"; then
    rm -rf -- "${staging}"
    red "無法辨識此備份格式，已取消還原。"
    return 1
  fi

  yellow "還原會覆蓋目前的 Home Assistant、MQTT 與監控設定。"
  echo "系統會先建立一份目前狀態的安全備份。"
  read -r -p "若要繼續，請輸入：還原設定 > " confirmation
  if [[ "${confirmation}" != "還原設定" ]]; then
    rm -rf -- "${staging}"
    echo "已取消，沒有變更任何資料。"
    return
  fi
  create_backup
  safety="$(find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
    -printf '%T@ %p\n' | sort -rn | head -n 1 | cut -d' ' -f2-)"

  systemctl stop vps-monitor 2>/dev/null || true
  systemctl stop vps-sentinel-controller 2>/dev/null || true
  docker stop homeassistant >/dev/null 2>&1 || true
  systemctl stop mosquitto 2>/dev/null || true
  apply_staging "${staging}"
  if ! start_and_validate; then
    recovery="$(mktemp -d)"
    tar -xzf "${safety}" -C "${recovery}"
    apply_staging "${recovery}"
    start_and_validate || true
    rm -rf -- "${recovery}" "${staging}"
    red "還原後驗證未通過，已自動回復還原前的設定。"
    echo "安全備份保留於：${safety}"
    return 1
  fi
  rm -rf -- "${staging}"
  green "設定已還原，Home Assistant、MQTT 與監控資料均通過驗證"
}

remove_old_backups() {
  local keep
  read -r -p "要保留最近幾份手動備份 [3]：" keep
  keep="${keep:-3}"
  [[ "${keep}" =~ ^[1-9][0-9]*$ ]] || {
    red "請輸入大於 0 的整數。"
    return
  }
  mapfile -t old_backups < <(
    find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
      -printf '%T@ %p\n' | sort -rn | tail -n "+$((keep + 1))" |
      cut -d' ' -f2-
  )
  for old_backup in "${old_backups[@]}"; do
    case "${old_backup}" in
      "${BACKUP_ROOT}/"*.tar.gz) rm -f -- "${old_backup}" ;;
    esac
  done
  green "清理完成，已保留最近 ${keep} 份手動備份"
}

while true; do
  clear
  printf '\033[1;35m'
  cat <<'BANNER'
╭────────────────────────────────────────╮
│  💾 VPS Sentinel 備份與還原            │
╰────────────────────────────────────────╯
BANNER
  printf '\033[0m'
  echo "  1. 查看現有備份"
  echo "  2. 建立設定備份"
  echo "  3. 還原設定備份"
  echo "  4. 清理舊備份"
  echo "  0. 返回上一層"
  read -r -p "請選擇 [0]：" choice
  case "${choice:-0}" in
    1) list_backups ;;
    2) create_backup ;;
    3) restore_backup ;;
    4) remove_old_backups ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 4。" ;;
  esac
  echo
  read -r -p "按 Enter 返回備份管理……" _
done
