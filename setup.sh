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
if [[ ! -f "${REPO_DIR}/update.sh" ]]; then
  red "找不到 update.sh，請先重新下載完整專案。"
  exit 1
fi
if [[ ! -f "${REPO_DIR}/uninstall.sh" ]]; then
  red "找不到 uninstall.sh，請先重新下載完整專案。"
  exit 1
fi
if [[ ! -f "${REPO_DIR}/manage.sh" ]]; then
  red "找不到 manage.sh，請先重新下載完整專案。"
  exit 1
fi
if [[ ! -f "${REPO_DIR}/upgrade.sh" || ! -f "${REPO_DIR}/VERSION" ||
      ! -f "${REPO_DIR}/doctor.sh" || ! -f "${REPO_DIR}/backup.sh" ||
      ! -f "${REPO_DIR}/automations.sh" ||
      ! -d "${REPO_DIR}/home-assistant/blueprints" ]]; then
  red "找不到升級工具或版本檔，請先重新下載完整專案。"
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
╭────────────────────────────────────────────╮
│  🖥️  VPS Sentinel 一條龍安裝              │
│  MQTT、Home Assistant 與 VPS 狀態監控      │
╰────────────────────────────────────────────╯
BANNER
printf '\033[0m'
echo
echo "安裝器會自動完成："
echo "  1. Mosquitto MQTT Broker 與專用帳號"
echo "  2. Home Assistant Container"
echo "  3. VPS Monitor 與開機自動啟動"
echo "  4. localhost-only MQTT 安全設定與服務檢查"
echo
echo "不會修改 UFW、雲端防火牆或既有服務的連接埠。"

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
case "${ID}:${VERSION_ID:-}" in
  ubuntu:22.04|ubuntu:24.04|debian:12|debian:13) ;;
  *)
    yellow "此版本不在主要測試範圍：${PRETTY_NAME}"
    yellow "安裝器會繼續，但部分套件名稱或設定可能不同。"
    ;;
esac

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
  tailscale_installer="$(mktemp)"
  echo "尚未安裝 Tailscale，將使用 Tailscale 官方安裝程式。"
  if ! curl -fL --retry 3 --proto '=https' --tlsv1.2 \
      https://tailscale.com/install.sh -o "${tailscale_installer}"; then
    rm -f -- "${tailscale_installer}"
    red "無法下載 Tailscale 官方安裝程式。"
    exit 1
  fi
  if ! bash -n "${tailscale_installer}"; then
    rm -f -- "${tailscale_installer}"
    red "Tailscale 安裝程式語法驗證失敗。"
    exit 1
  fi
  bash "${tailscale_installer}"
  rm -f -- "${tailscale_installer}"
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
  red "Mosquitto 重啟後未保持運作，最近的日誌如下："
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
ha_new_install=false
if [[ ! -e "${HA_DIR}/compose.yaml" ]]; then
  ha_new_install=true
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
  if [[ "${ha_new_install}" == "true" ]]; then
    docker compose pull
  fi
  docker compose up -d
)
green "Home Assistant Container 已啟動"

ha_url="http://${tailscale_ip}:8123"
serve_usable=false
if tailscale serve --bg http://127.0.0.1:8123 &&
   tailscale serve status 2>/dev/null |
     grep -q '127.0.0.1:8123'; then
  if grep -q '^[[:space:]]*server_host:' \
      "${HA_DIR}/config/configuration.yaml" &&
     grep -Fq "    - ${tailscale_ip}" \
      "${HA_DIR}/config/configuration.yaml"; then
    backup_if_exists "${HA_DIR}/config/configuration.yaml"
    if ! grep -q '^[[:space:]]*use_x_forwarded_for:' \
        "${HA_DIR}/config/configuration.yaml"; then
      sed -i '/^[[:space:]]*server_host:[[:space:]]*$/i\
  use_x_forwarded_for: true\
  trusted_proxies:\
    - 127.0.0.1' "${HA_DIR}/config/configuration.yaml"
    fi
    escaped_ip="${tailscale_ip//./\\.}"
    sed -Ei \
      "/^[[:space:]]*-[[:space:]]*${escaped_ip}[[:space:]]*$/d" \
      "${HA_DIR}/config/configuration.yaml"
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    )
    green "Home Assistant 已改由 Tailscale Serve 私有 HTTPS 存取"
    serve_usable=true
  elif grep -q '^[[:space:]]*use_x_forwarded_for:[[:space:]]*true' \
      "${HA_DIR}/config/configuration.yaml" &&
       grep -q '^[[:space:]]*-[[:space:]]*127\.0\.0\.1[[:space:]]*$' \
      "${HA_DIR}/config/configuration.yaml"; then
    serve_usable=true
  else
    yellow "既有 Home Assistant HTTP 設定不是由本安裝器管理。"
    yellow "為避免破壞自訂設定，未自動切換至 Tailscale Serve 網址。"
  fi
  if [[ "${serve_usable}" == "true" ]]; then
    tailscale_dns="$(tailscale status --json 2>/dev/null |
      python3 -c \
        'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' \
        2>/dev/null || true)"
    if [[ -n "${tailscale_dns}" ]]; then
      ha_url="https://${tailscale_dns}"
    fi
  fi
else
  yellow "Tailscale Serve 尚未啟用，暫時沿用 Tailscale IP 存取。"
  yellow "之後可重新執行安裝器再次設定。"
fi

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
  echo "  1) 極省資源：每 60 秒更新資源"
  echo "  2) 平衡模式：每 15 秒更新資源（推薦）"
  echo "  3) 即時監控：每 10 秒更新資源"
  profile=""
  ask profile "請選擇" "2"
  case "${profile}" in
    1) interval=60; health=900; updates=86400; samples=5 ;;
    2) interval=15; health=300; updates=86400; samples=20 ;;
    3) interval=10; health=60; updates=21600; samples=30 ;;
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
requirements_hash="$(sha256sum "${MONITOR_DIR}/requirements.txt" | awk '{print $1}')"
installed_hash="$(cat "${MONITOR_DIR}/.requirements.sha256" 2>/dev/null || true)"
if [[ ! -x "${MONITOR_DIR}/venv/bin/python" ||
      "${requirements_hash}" != "${installed_hash}" ]]; then
  echo "Python 依賴有變更，正在建立執行環境。"
  systemctl stop vps-monitor 2>/dev/null || true
  python3 -m venv --clear "${MONITOR_DIR}/venv"
  "${MONITOR_DIR}/venv/bin/pip" install --disable-pip-version-check \
    -r "${MONITOR_DIR}/requirements.txt"
  printf '%s\n' "${requirements_hash}" > \
    "${MONITOR_DIR}/.requirements.sha256"
else
  green "Python 依賴未變更，略過重複安裝"
fi
install -m 0644 "${REPO_DIR}/vps-monitor/vps-monitor.service" \
  /etc/systemd/system/vps-monitor.service
systemctl daemon-reload
systemctl enable vps-monitor
systemctl restart vps-monitor
green "VPS Monitor 已啟動並設為開機自動執行"
install -m 0755 "${REPO_DIR}/update.sh" \
  /usr/local/sbin/vps-sentinel-update
install -m 0755 "${REPO_DIR}/uninstall.sh" \
  /usr/local/sbin/vps-sentinel-uninstall
install -m 0755 "${REPO_DIR}/manage.sh" \
  /usr/local/sbin/vps-sentinel
install -m 0755 "${REPO_DIR}/upgrade.sh" \
  /usr/local/sbin/vps-sentinel-upgrade
install -m 0755 "${REPO_DIR}/doctor.sh" \
  /usr/local/sbin/vps-sentinel-doctor
install -m 0755 "${REPO_DIR}/backup.sh" \
  /usr/local/sbin/vps-sentinel-backup
install -m 0755 "${REPO_DIR}/automations.sh" \
  /usr/local/sbin/vps-sentinel-automations
install -d -m 0755 "${MONITOR_DIR}/blueprints"
install -m 0644 "${REPO_DIR}"/home-assistant/blueprints/*.yaml \
  "${MONITOR_DIR}/blueprints/"
install -m 0644 "${REPO_DIR}/VERSION" "${MONITOR_DIR}/.version"

blue "步驟 6/6：最後檢查"
sleep 3
checks_failed=false
for service in docker mosquitto vps-monitor; do
  if systemctl is-active --quiet "${service}"; then
    green "${service}：正常"
  else
    red "${service}：未運作"
    checks_failed=true
  fi
done
if docker ps --format '{{.Names}}' | grep -qx homeassistant; then
  green "homeassistant：正常"
else
  red "homeassistant：未運作"
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
echo "Home Assistant： ${ha_url}"
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
echo
echo "日後只要執行 sudo vps-sentinel，即可進入中文維護中心："
echo "  📊 查看系統狀態"
echo "  ⚙️  調整監控設定"
echo "  🏠 管理 Home Assistant"
echo "  🧰 更新、備份、修復或移除"
echo
echo "快速查看狀態：sudo vps-sentinel status"
echo "一鍵健康檢查：sudo vps-sentinel-doctor"
echo "日後更新 Home Assistant：sudo vps-sentinel-update"
echo "日後完整移除：sudo vps-sentinel-uninstall"
