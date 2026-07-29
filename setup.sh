#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_DIR
readonly HA_DIR="/opt/homeassistant"
readonly MONITOR_DIR="/opt/vps-monitor"
readonly MQTT_CONF="/etc/mosquitto/conf.d/home-assistant.conf"
readonly MQTT_PASSWD="/etc/mosquitto/passwd"
readonly MONITOR_ENV="/etc/vps-monitor.env"
readonly CREDENTIALS_FILE="/root/vps-homeassistant-credentials.txt"

blue()   { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

failed() {
  red "安裝在第 $1 行中斷。已完成的服務與資料不會被刪除。"
  red "修正畫面上的錯誤後，可直接重新執行本安裝器。"
}
trap 'failed "$LINENO"' ERR

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo bash setup.sh"
  exit 1
fi

if [[ ! -t 0 ]]; then
  red "這是互動式中文安裝器，請直接在終端機執行。"
  exit 1
fi

if [[ ! -f "${REPO_DIR}/vps-monitor/vps_monitor.py" ]]; then
  red "專案檔案不完整，請在 repository 根目錄執行 setup.sh。"
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

ask() {
  local result_var="$1" question="$2" default_value="${3-}" answer
  if [[ -n "${default_value}" ]]; then
    read -r -p "${question} [${default_value}]：" answer
    answer="${answer:-${default_value}}"
  else
    while [[ -z "${answer:-}" ]]; do
      read -r -p "${question}：" answer
    done
  fi
  printf -v "${result_var}" '%s' "${answer}"
}

ask_secret() {
  local result_var="$1" question="$2" answer
  while [[ -z "${answer:-}" ]]; do
    read -r -s -p "${question}：" answer
    printf '\n'
  done
  printf -v "${result_var}" '%s' "${answer}"
}

env_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "${value}"
}

backup_if_exists() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    local backup
    backup="${path}.backup.$(date +%Y%m%d-%H%M%S)"
    cp -a "${path}" "${backup}"
    green "已備份：${backup}"
  fi
}

clear
printf '\033[1;35m'
cat <<'BANNER'
========================================================
 VPS Monitor 一條龍中文安裝器
 Mosquitto + Home Assistant + VPS 狀態監控
========================================================
BANNER
printf '\033[0m'
echo
echo "安裝器會自動完成："
echo "  1. Mosquitto MQTT Broker 與專用帳號"
echo "  2. Home Assistant Container"
echo "  3. VPS Monitor 與開機自動啟動"
echo "  4. localhost-only MQTT 安全設定與服務檢查"
echo
echo "不會修改 UFW、雲端防火牆或 3X-UI 連接埠。"

proceed=""
ask_yes_no proceed "是否開始" "yes"
[[ "${proceed}" == "true" ]] || exit 0

blue "步驟 1/6：檢查 VPS"
if [[ ! -r /etc/os-release ]]; then
  red "無法辨識作業系統。目前正式支援 Ubuntu LTS，並提供 Debian 實驗性支援。"
  exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" ]]; then
  red "不支援此作業系統：${PRETTY_NAME:-unknown}"
  red "目前正式支援 Ubuntu LTS，並提供 Debian 12/13 實驗性支援。"
  exit 1
fi
if [[ "${ID}" == "debian" ]]; then
  yellow "目前執行於 ${PRETTY_NAME}；Debian 屬於實驗性支援平台。"
fi

memory_mb="$(awk '/MemTotal/ {printf "%d", $2 / 1024}' /proc/meminfo)"
disk_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
echo "系統：${PRETTY_NAME}"
echo "記憶體：${memory_mb} MB"
echo "根目錄可用：${disk_mb} MB"
if (( memory_mb < 900 )); then
  yellow "記憶體低於 1 GB，Home Assistant 可能不穩定。"
fi
if (( disk_mb < 4096 )); then
  red "根目錄可用空間低於 4 GB，請先清理磁碟。"
  exit 1
fi
green "基本資源檢查完成"

blue "步驟 2/6：安裝必要套件"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git mosquitto mosquitto-clients openssl \
  python3 python3-pip python3-venv

if ! command -v docker >/dev/null 2>&1; then
  echo "尚未安裝 Docker，正在安裝 Ubuntu/Debian 套件版本。"
  apt-get install -y docker.io
fi

if ! docker compose version >/dev/null 2>&1; then
  if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
    apt-get install -y docker-compose-v2
  elif apt-cache show docker-compose-plugin >/dev/null 2>&1; then
    apt-get install -y docker-compose-plugin
  else
    red "找不到 Docker Compose v2 套件，請先依 Docker 官方文件安裝。"
    exit 1
  fi
fi
systemctl enable --now docker
green "必要套件已就緒"

blue "設定 Tailscale 安全連線"
if ! command -v tailscale >/dev/null 2>&1; then
  echo "尚未安裝 Tailscale，將使用 Tailscale 官方安裝程式。"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

tailscale_ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
if [[ -z "${tailscale_ip}" ]]; then
  echo
  echo "接下來終端機會顯示 Tailscale 登入網址。"
  echo "請用瀏覽器開啟網址，登入並授權這台 VPS。"
  echo
  tailscale up
  tailscale_ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "${tailscale_ip}" ]]; then
  red "尚未取得 Tailscale IP。完成授權後請重新執行 setup.sh。"
  exit 1
fi
green "Tailscale 已連線：${tailscale_ip}"

blue "步驟 3/6：設定 Mosquitto"
generated_ha_password=""
generated_monitor_password=""
install -d -m 0755 /etc/mosquitto/conf.d

if [[ ! -e "${MQTT_PASSWD}" ]]; then
  generated_ha_password="$(openssl rand -hex 18)"
  generated_monitor_password="$(openssl rand -hex 18)"
  mosquitto_passwd -b -c "${MQTT_PASSWD}" home-assistant \
    "${generated_ha_password}"
  mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
    "${generated_monitor_password}"
  green "已自動建立兩個 MQTT 專用帳號"
else
  if ! grep -q '^home-assistant:' "${MQTT_PASSWD}"; then
    generated_ha_password="$(openssl rand -hex 18)"
    mosquitto_passwd -b "${MQTT_PASSWD}" home-assistant \
      "${generated_ha_password}"
    green "已新增 home-assistant MQTT 帳號"
  fi
  if ! grep -q '^vps-monitor:' "${MQTT_PASSWD}"; then
    generated_monitor_password="$(openssl rand -hex 18)"
    mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
      "${generated_monitor_password}"
    green "已新增 vps-monitor MQTT 帳號"
  fi
fi

chown root:mosquitto "${MQTT_PASSWD}"
chmod 0640 "${MQTT_PASSWD}"
backup_if_exists "${MQTT_CONF}"
cat > "${MQTT_CONF}" <<'MQTT'
per_listener_settings false
allow_anonymous false
password_file /etc/mosquitto/passwd

# Home Assistant 與監控器都在本機，不對公網開放 MQTT。
listener 1883 127.0.0.1
MQTT

systemctl enable mosquitto
if ! systemctl restart mosquitto; then
  red "Mosquitto 無法套用設定，最近的日誌如下："
  journalctl -u mosquitto -n 50 --no-pager || true
  exit 1
fi
if ! systemctl is-active --quiet mosquitto; then
  red "Mosquitto 重啟後未保持運行，最近的日誌如下："
  journalctl -u mosquitto -n 50 --no-pager || true
  exit 1
fi
green "Mosquitto 已啟動，只監聽 127.0.0.1:1883"

if [[ -n "${generated_ha_password}" || -n "${generated_monitor_password}" ]]; then
  umask 077
  {
    echo "VPS Monitor 安裝憑證"
    echo "建立時間：$(date --iso-8601=seconds)"
    echo
    [[ -n "${generated_ha_password}" ]] && \
      echo "Home Assistant MQTT 使用者：home-assistant"
    [[ -n "${generated_ha_password}" ]] && \
      echo "Home Assistant MQTT 密碼：${generated_ha_password}"
    [[ -n "${generated_monitor_password}" ]] && \
      echo "VPS Monitor MQTT 使用者：vps-monitor"
    [[ -n "${generated_monitor_password}" ]] && \
      echo "VPS Monitor MQTT 密碼：${generated_monitor_password}"
  } > "${CREDENTIALS_FILE}"
  chmod 0600 "${CREDENTIALS_FILE}"
  green "新密碼已保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
fi

blue "步驟 4/6：部署 Home Assistant"
install -d -m 0755 "${HA_DIR}/config"
if [[ ! -e "${HA_DIR}/compose.yaml" ]]; then
  cat > "${HA_DIR}/compose.yaml" <<'COMPOSE'
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    restart: unless-stopped
    network_mode: host
    environment:
      TZ: Asia/Taipei
    volumes:
      - /opt/homeassistant/config:/config
COMPOSE
  green "已建立 Home Assistant Compose 設定"
else
  green "沿用既有 ${HA_DIR}/compose.yaml"
fi

if [[ ! -e "${HA_DIR}/config/configuration.yaml" ]]; then
  install -d -m 0755 "${HA_DIR}/config/themes"
  cat > "${HA_DIR}/config/configuration.yaml" <<HAYAML
default_config:

frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

http:
  server_host:
    - 127.0.0.1
    - ${tailscale_ip}
  ip_ban_enabled: true
  login_attempts_threshold: 5
HAYAML
  printf '[]\n' > "${HA_DIR}/config/automations.yaml"
  printf '{}\n' > "${HA_DIR}/config/scripts.yaml"
  printf '{}\n' > "${HA_DIR}/config/scenes.yaml"
elif ! grep -q '^[[:space:]]*http:' \
  "${HA_DIR}/config/configuration.yaml"; then
  backup_if_exists "${HA_DIR}/config/configuration.yaml"
  cat >> "${HA_DIR}/config/configuration.yaml" <<HAYAML

http:
  server_host:
    - 127.0.0.1
    - ${tailscale_ip}
  ip_ban_enabled: true
  login_attempts_threshold: 5
HAYAML
  green "已將 Home Assistant 限制為 localhost 與 Tailscale"
fi

(
  cd "${HA_DIR}"
  docker compose config >/dev/null
  docker compose pull
  docker compose up -d
)
green "Home Assistant Container 已啟動"

blue "步驟 5/6：設定 VPS Monitor"
if [[ -e "${MONITOR_ENV}" ]]; then
  green "沿用既有 ${MONITOR_ENV}"
else
  if [[ -z "${generated_monitor_password}" ]]; then
    ask_secret generated_monitor_password \
      "請輸入既有 vps-monitor MQTT 密碼（輸入時不顯示）"
  fi

  default_id="$(hostname -s | tr '[:upper:]' '[:lower:]' |
    sed 's/[^a-z0-9_-]/-/g')"
  vps_name=""
  vps_id=""
  ask vps_name "Home Assistant 中的 VPS 名稱" "$(hostname -s)"
  ask vps_id "VPS 識別 ID（小寫英文、數字、_、-）" "${default_id}"
  if [[ ! "${vps_id}" =~ ^[a-z0-9_-]+$ ]]; then
    red "VPS 識別 ID 格式不正確。"
    exit 1
  fi

  echo "資源模式："
  echo "  1) 極省資源：5 分鐘回報"
  echo "  2) 平衡模式：2 分鐘回報（推薦）"
  echo "  3) 即時監控：30 秒回報"
  profile=""
  ask profile "請選擇" "2"
  case "${profile}" in
    1) interval=300; health=900; updates=86400; samples=2 ;;
    2) interval=120; health=300; updates=86400; samples=3 ;;
    3) interval=30;  health=60;  updates=21600; samples=10 ;;
    *) red "請選擇 1、2 或 3。"; exit 1 ;;
  esac

  services="ssh mosquitto docker"
  umask 077
  {
    echo "# 由 setup.sh 產生：$(date --iso-8601=seconds)"
    printf 'MQTT_HOST="127.0.0.1"\n'
    printf 'MQTT_PORT="1883"\n'
    printf 'MQTT_USERNAME="vps-monitor"\n'
    printf 'MQTT_PASSWORD=%s\n' "$(env_quote "${generated_monitor_password}")"
    printf 'MQTT_TLS="false"\n'
    printf 'MQTT_CA_FILE=""\n'
    printf 'VPS_ID=%s\n' "$(env_quote "${vps_id}")"
    printf 'VPS_NAME=%s\n' "$(env_quote "${vps_name}")"
    printf 'PUBLISH_INTERVAL="%s"\n' "${interval}"
    printf 'HEALTH_CHECK_INTERVAL="%s"\n' "${health}"
    printf 'UPDATE_CHECK_INTERVAL="%s"\n' "${updates}"
    printf 'MONITOR_NETWORK="false"\n'
    printf 'DISCOVERY_PREFIX="homeassistant"\n'
    printf 'CPU_WARN_PERCENT="90"\n'
    printf 'MEMORY_WARN_PERCENT="90"\n'
    printf 'DISK_WARN_PERCENT="85"\n'
    printf 'OVERLOAD_SAMPLES="%s"\n' "${samples}"
    printf 'WATCH_SERVICES=%s\n' "$(env_quote "${services}")"
  } > "${MONITOR_ENV}"
  chmod 0600 "${MONITOR_ENV}"
fi

install -d -m 0755 "${MONITOR_DIR}"
install -m 0755 "${REPO_DIR}/vps-monitor/vps_monitor.py" \
  "${MONITOR_DIR}/vps_monitor.py"
install -m 0644 "${REPO_DIR}/vps-monitor/requirements.txt" \
  "${MONITOR_DIR}/requirements.txt"
python3 -m venv "${MONITOR_DIR}/venv"
"${MONITOR_DIR}/venv/bin/pip" install --disable-pip-version-check \
  -r "${MONITOR_DIR}/requirements.txt"
install -m 0644 "${REPO_DIR}/vps-monitor/vps-monitor.service" \
  /etc/systemd/system/vps-monitor.service
systemctl daemon-reload
systemctl enable --now vps-monitor
green "VPS Monitor 已啟動並設為開機自動執行"

blue "步驟 6/6：最後檢查"
sleep 3
checks_failed=false
for service in docker mosquitto vps-monitor; do
  if systemctl is-active --quiet "${service}"; then
    green "${service}：正常"
  else
    red "${service}：未運行"
    checks_failed=true
  fi
done
if docker ps --format '{{.Names}}' | grep -qx homeassistant; then
  green "homeassistant：正常"
else
  red "homeassistant：未運行"
  checks_failed=true
fi

if [[ "${checks_failed}" == "true" ]]; then
  echo
  echo "排錯指令："
  echo "  journalctl -u mosquitto -n 50 --no-pager"
  echo "  journalctl -u vps-monitor -n 50 --no-pager"
  echo "  docker logs homeassistant --tail 50"
  exit 1
fi

echo
printf '\033[1;32m%s\033[0m\n' \
  "========================================================"
printf '\033[1;32m%s\033[0m\n' " 安裝完成"
printf '\033[1;32m%s\033[0m\n' \
  "========================================================"
echo
echo "Home Assistant： http://${tailscale_ip}:8123"
echo
echo "第一次使用仍需完成兩個畫面操作："
echo "  1. 開啟上方網址，建立 Home Assistant 管理員"
echo "  2. 設定 → 裝置與服務 → 新增 MQTT"
echo
echo "MQTT 填寫："
echo "  Broker：127.0.0.1"
echo "  Port：1883"
echo "  Username：home-assistant"
if [[ -n "${generated_ha_password}" ]]; then
  echo "  Password：請執行 sudo cat ${CREDENTIALS_FILE} 查看"
else
  echo "  Password：使用你現有的 home-assistant MQTT 密碼"
fi
echo "  TLS：關閉"
echo
echo "完成 MQTT 整合後，VPS 裝置會自動出現。"
