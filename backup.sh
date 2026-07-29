#!/usr/bin/env bash
set -Eeuo pipefail

readonly BACKUP_ROOT="/opt/vps-sentinel-backups"
readonly HA_DIR="/opt/homeassistant"
readonly ENV_FILE="/etc/vps-monitor.env"
readonly MONITOR_DIR="/opt/vps-monitor"
readonly SERVICE_FILE="/etc/systemd/system/vps-monitor.service"

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

apply_staging() {
  local source="$1"
  if [[ -d "${source}/homeassistant" ]]; then
    case "${HA_DIR}/config" in
      /opt/homeassistant/config)
        rm -rf -- "${HA_DIR}/config"
        install -d -m 0755 "${HA_DIR}/config"
        ;;
      *) red "Home Assistant 路徑驗證失敗"; return 1 ;;
    esac
    cp -a "${source}/homeassistant/." "${HA_DIR}/config/"
    if [[ -f "${source}/homeassistant/docker-compose.yml" ]]; then
      mv -f "${HA_DIR}/config/docker-compose.yml" \
        "${HA_DIR}/docker-compose.yml"
    fi
  fi
  if [[ -f "${source}/monitor/vps-monitor.env" ]]; then
    install -m 0600 "${source}/monitor/vps-monitor.env" "${ENV_FILE}"
  fi
}

start_and_validate() {
  systemctl start vps-monitor 2>/dev/null || true
  if [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    (cd "${HA_DIR}" && docker compose up -d homeassistant)
  fi
  systemctl is-active --quiet vps-monitor &&
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
  local timestamp staging archive
  timestamp="$(date +%Y%m%d-%H%M%S)"
  staging="$(mktemp -d)"
  archive="${BACKUP_ROOT}/settings-${timestamp}.tar.gz"

  install -d -m 0700 "${staging}/homeassistant" \
    "${staging}/monitor"
  if [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    cp -a "${HA_DIR}/docker-compose.yml" "${staging}/homeassistant/"
  fi
  if [[ -d "${HA_DIR}/config" ]]; then
    tar -C "${HA_DIR}/config" \
      --exclude='home-assistant_v2.db*' \
      --exclude='home-assistant.log*' \
      --exclude='*.log' \
      --exclude='tts' \
      -cf - . | tar -C "${staging}/homeassistant" -xf -
  fi
  [[ ! -f "${ENV_FILE}" ]] ||
    install -m 0600 "${ENV_FILE}" "${staging}/monitor/vps-monitor.env"
  [[ ! -f "${SERVICE_FILE}" ]] ||
    cp -a "${SERVICE_FILE}" "${staging}/monitor/"
  if [[ -f "${MONITOR_DIR}/.version" ]]; then
    cp -a "${MONITOR_DIR}/.version" "${staging}/monitor/"
  fi
  {
    echo "format=1"
    echo "created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "kind=settings"
  } > "${staging}/MANIFEST"
  tar -C "${staging}" -czf "${archive}" .
  chmod 0600 "${archive}"
  rm -rf -- "${staging}"
  green "設定備份已建立：${archive}"
  echo "為節省空間，歷史資料庫與日誌不包含在此備份中。"
}

restore_backup() {
  local -a archives=()
  local choice archive staging safety
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
    printf '  %d) %s\n' "$((index + 1))" "$(basename "${archives[index]}")"
  done
  echo "  0) 取消"
  read -r -p "請選擇：" choice
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
  trap 'rm -rf -- "${staging}"' RETURN
  tar -xzf "${archive}" -C "${staging}"
  if [[ ! -f "${staging}/MANIFEST" ]] ||
     ! grep -qx 'format=1' "${staging}/MANIFEST"; then
    red "無法辨識此備份格式，已取消還原。"
    return 1
  fi

  yellow "還原會覆蓋目前的 Home Assistant 設定與監控環境檔。"
  echo "系統會先建立一份目前狀態的安全備份。"
  read -r -p "若要繼續，請輸入：還原設定 > " confirmation
  [[ "${confirmation}" == "還原設定" ]] || {
    echo "已取消，沒有變更任何資料。"
    return
  }
  create_backup
  safety="$(find "${BACKUP_ROOT}" -maxdepth 1 -type f -name '*.tar.gz' \
    -printf '%T@ %p\n' | sort -rn | head -n 1 | cut -d' ' -f2-)"

  systemctl stop vps-monitor 2>/dev/null || true
  if docker inspect homeassistant >/dev/null 2>&1; then
    docker stop homeassistant >/dev/null
  fi
  apply_staging "${staging}"
  if ! start_and_validate; then
    local recovery
    recovery="$(mktemp -d)"
    tar -xzf "${safety}" -C "${recovery}"
    apply_staging "${recovery}"
    start_and_validate || true
    rm -rf -- "${recovery}"
    red "還原後驗證未通過，已自動回復還原前的設定。"
    echo "安全備份保留於：${safety}"
    return 1
  fi
  green "設定已還原並通過基本驗證"
  rm -rf -- "${staging}"
  trap - RETURN
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
========================================================
 VPS Sentinel 備份管理
========================================================
BANNER
  printf '\033[0m'
  echo "  1) 查看設定備份"
  echo "  2) 建立設定備份"
  echo "  3) 還原設定備份"
  echo "  4) 清理舊備份"
  echo "  0) 返回"
  read -r -p "請選擇：" choice
  case "${choice}" in
    1) list_backups ;;
    2) create_backup ;;
    3) restore_backup ;;
    4) remove_old_backups ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 4。" ;;
  esac
  echo
  read -r -p "按 Enter 繼續……" _
done
