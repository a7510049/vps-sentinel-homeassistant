#!/usr/bin/env bash
set -Eeuo pipefail

readonly HA_DIR="/opt/homeassistant"
readonly BACKUP_DIR="/opt/homeassistant-backups"
readonly MONITOR_DIR="/opt/vps-monitor"
readonly MONITOR_ENV="/etc/vps-monitor.env"
readonly MONITOR_SERVICE="/etc/systemd/system/vps-monitor.service"
readonly MQTT_CONF="/etc/mosquitto/conf.d/home-assistant.conf"
readonly MQTT_PASSWD="/etc/mosquitto/passwd"
readonly CREDENTIALS_FILE="/root/vps-homeassistant-credentials.txt"
readonly UPDATE_COMMAND="/usr/local/sbin/vps-sentinel-update"
readonly UNINSTALL_COMMAND="/usr/local/sbin/vps-sentinel-uninstall"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel-uninstall"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "為避免誤刪資料，移除工具只能在互動式終端機執行。"
  exit 1
fi

ask_yes_no() {
  local result_var="$1" question="$2" default_answer="$3" answer hint
  [[ "${default_answer}" == "yes" ]] && hint="Y/n" || hint="y/N"
  while true; do
    read -r -p "${question} [${hint}]：" answer
    answer="${answer:-${default_answer}}"
    case "${answer,,}" in
      y|yes|是) printf -v "${result_var}" 'true'; return ;;
      n|no|否)  printf -v "${result_var}" 'false'; return ;;
      *) yellow "請輸入 y 或 n。" ;;
    esac
  done
}

remove_tree() {
  local target="$1"
  case "${target}" in
    "${HA_DIR}"|"${BACKUP_DIR}"|"${MONITOR_DIR}")
      rm -rf -- "${target}"
      ;;
    *)
      red "安全檢查拒絕刪除非專案路徑：${target}"
      return 1
      ;;
  esac
}

remove_monitor() {
  systemctl disable --now vps-monitor >/dev/null 2>&1 || true
  rm -f -- "${MONITOR_SERVICE}" "${MONITOR_ENV}"
  remove_tree "${MONITOR_DIR}"
  systemctl daemon-reload
  systemctl reset-failed vps-monitor >/dev/null 2>&1 || true
  green "VPS Monitor 程式、設定與 systemd 服務已移除"
}

create_final_backup() {
  local timestamp backup candidate
  local -a items=()
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup="/root/vps-sentinel-final-backup-${timestamp}.tar.gz"

  for candidate in \
    opt/homeassistant \
    opt/homeassistant-backups \
    etc/vps-monitor.env \
    root/vps-homeassistant-credentials.txt \
    etc/mosquitto/conf.d/home-assistant.conf \
    etc/mosquitto/passwd; do
    [[ -e "/${candidate}" ]] && items+=("${candidate}")
  done
  for candidate in /etc/mosquitto/conf.d/home-assistant.conf.backup.*; do
    [[ -e "${candidate}" ]] && items+=("${candidate#/}")
  done

  if (( ${#items[@]} == 0 )); then
    yellow "找不到可備份的專案資料，略過備份"
    return
  fi
  tar -C / -czf "${backup}" "${items[@]}"
  chmod 0600 "${backup}"
  green "最終備份已保存：${backup}"
}

remove_home_assistant() {
  if command -v docker >/dev/null 2>&1; then
    if [[ -f "${HA_DIR}/compose.yaml" ]] &&
       docker compose version >/dev/null 2>&1; then
      (
        cd "${HA_DIR}"
        docker compose stop homeassistant >/dev/null 2>&1 || true
        docker compose rm -f homeassistant >/dev/null 2>&1 || true
      )
    elif docker ps -a --format '{{.Names}}' 2>/dev/null |
         grep -qx homeassistant; then
      docker rm -f homeassistant >/dev/null
    fi
  fi
  remove_tree "${HA_DIR}"
  remove_tree "${BACKUP_DIR}"
  green "Home Assistant Container、設定與自動備份已移除"
}

remove_mqtt_settings() {
  local candidate mqtt_shared=false
  if command -v mosquitto_passwd >/dev/null 2>&1 &&
     [[ -f "${MQTT_PASSWD}" ]]; then
    mosquitto_passwd -D "${MQTT_PASSWD}" home-assistant \
      >/dev/null 2>&1 || true
    mosquitto_passwd -D "${MQTT_PASSWD}" vps-monitor \
      >/dev/null 2>&1 || true
    if ! grep -Eq '^[^#[:space:]][^:]*:' "${MQTT_PASSWD}"; then
      rm -f -- "${MQTT_PASSWD}"
    else
      mqtt_shared=true
    fi
  fi
  if [[ "${mqtt_shared}" == "true" ]]; then
    yellow "MQTT 密碼檔仍有其他帳號，保留 Broker 設定以免影響其他服務"
  else
    rm -f -- "${MQTT_CONF}"
    for candidate in "${MQTT_CONF}".backup.*; do
      [[ -e "${candidate}" ]] && rm -f -- "${candidate}"
    done
  fi
  if systemctl is-active --quiet mosquitto 2>/dev/null; then
    systemctl restart mosquitto || \
      yellow "Mosquitto 無法重新啟動，請執行 journalctl -u mosquitto 檢查"
  fi
  green "專案建立的 MQTT 專用帳號已移除"
  [[ "${mqtt_shared}" == "true" ]] ||
    green "專案建立的 MQTT 設定與設定備份已移除"
}

remove_tailscale_serve() {
  if command -v tailscale >/dev/null 2>&1 &&
     tailscale serve status 2>/dev/null |
       grep -q '127.0.0.1:8123'; then
    if tailscale serve --https=443 off >/dev/null 2>&1; then
      green "Home Assistant 的 Tailscale Serve 規則已移除"
    else
      yellow "無法自動移除 Tailscale Serve，請執行 tailscale serve status 檢查"
    fi
  fi
}

remove_unused_packages() {
  local remove_mosquitto remove_docker
  local mqtt_custom=false
  local -a containers=()
  local -a installed_packages=()

  if command -v mosquitto >/dev/null 2>&1; then
    if find /etc/mosquitto/conf.d -maxdepth 1 -type f -name '*.conf' \
        -print -quit 2>/dev/null | grep -q . ||
       [[ -s "${MQTT_PASSWD}" ]]; then
      mqtt_custom=true
    fi
    if [[ "${mqtt_custom}" == "true" ]]; then
      yellow "偵測到其他 MQTT 設定或帳號，保留 Mosquitto 套件"
    else
      remove_mosquitto=""
      ask_yes_no remove_mosquitto \
        "未偵測到其他 MQTT 用途，是否一併移除 Mosquitto 套件" "no"
      if [[ "${remove_mosquitto}" == "true" ]]; then
        systemctl disable --now mosquitto >/dev/null 2>&1 || true
        installed_packages=()
        for package in mosquitto mosquitto-clients; do
          dpkg-query -W -f='${db:Status-Status}' "${package}" \
            2>/dev/null | grep -qx installed &&
            installed_packages+=("${package}")
        done
        (( ${#installed_packages[@]} == 0 )) ||
          apt-get purge -y "${installed_packages[@]}"
        green "Mosquitto 套件已移除"
      fi
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    mapfile -t containers < <(docker ps -a --format '{{.Names}}')
    if (( ${#containers[@]} > 0 )); then
      yellow "Docker 仍有其他 Container，為避免誤刪，保留 Docker 套件："
      printf '  - %s\n' "${containers[@]}"
    else
      remove_docker=""
      ask_yes_no remove_docker \
        "未偵測到其他 Container，是否一併移除 Docker 套件" "no"
      if [[ "${remove_docker}" == "true" ]]; then
        systemctl disable --now docker >/dev/null 2>&1 || true
        installed_packages=()
        for package in docker.io docker-compose-v2 docker-compose-plugin \
          containerd runc; do
          dpkg-query -W -f='${db:Status-Status}' "${package}" \
            2>/dev/null | grep -qx installed &&
            installed_packages+=("${package}")
        done
        (( ${#installed_packages[@]} == 0 )) ||
          apt-get purge -y "${installed_packages[@]}"
        yellow "Docker 映像與 volume 可能仍在 /var/lib/docker，未自動刪除"
        green "Docker 套件已移除"
      fi
    fi
  fi

  yellow "Tailscale 軟體與登入狀態已保留，避免中斷目前的 VPS 連線。"
  echo "若確定不再使用，請從主機商 Console 另行移除 Tailscale。"
}

clear
printf '\033[1;35m'
cat <<'BANNER'
========================================================
 VPS Sentinel 中文移除工具
========================================================
BANNER
printf '\033[0m'
echo
echo "請選擇移除範圍："
echo "  1) 只移除 VPS Monitor（保留 Home Assistant 與 MQTT）"
echo "  2) 完整移除本專案建立的環境與資料"
echo "  3) 取消"
echo
read -r -p "請選擇 [1]：" choice
choice="${choice:-1}"

case "${choice}" in
  1)
    remove_monitor
    echo
    green "移除完成。Home Assistant、MQTT 與 Tailscale 不受影響。"
    ;;
  2)
    echo
    red "完整移除會永久刪除 Home Assistant 設定、歷史資料與自動備份。"
    echo "若要繼續，請完整輸入：完整移除"
    read -r -p "> " confirmation
    if [[ "${confirmation}" != "完整移除" ]]; then
      yellow "確認文字不符，已取消，沒有刪除任何資料。"
      exit 0
    fi

    keep_backup=""
    ask_yes_no keep_backup \
      "刪除前是否建立一份 root 專用的最終備份" "yes"
    [[ "${keep_backup}" == "true" ]] && create_final_backup

    remove_monitor
    remove_home_assistant
    remove_mqtt_settings
    remove_tailscale_serve
    rm -f -- "${CREDENTIALS_FILE}" "${UPDATE_COMMAND}"

    remove_packages=""
    ask_yes_no remove_packages \
      "是否檢查並移除已無其他用途的共用套件" "no"
    [[ "${remove_packages}" == "true" ]] && remove_unused_packages

    rm -f -- "${UNINSTALL_COMMAND}"
    echo
    green "VPS Sentinel 管理的環境與資料已完整移除。"
    [[ "${keep_backup}" == "true" ]] && \
      echo "需要復原時，請使用上方顯示的最終備份。"
    ;;
  3)
    echo "已取消，沒有刪除任何資料。"
    ;;
  *)
    red "請選擇 1、2 或 3。"
    exit 1
    ;;
esac
