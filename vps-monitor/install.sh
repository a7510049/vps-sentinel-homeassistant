#!/usr/bin/env bash
set -Eeuo pipefail

readonly INSTALL_DIR="/opt/vps-monitor"
readonly ENV_FILE="/etc/vps-monitor.env"
readonly SERVICE_FILE="/etc/systemd/system/vps-monitor.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Values are assigned indirectly by the prompt helpers.
reuse_config=""
mqtt_host=""
mqtt_tls=""
mqtt_port=""
mqtt_username=""
mqtt_password=""
vps_id=""
vps_name=""
services=""
monitor_network=""
cpu_warn=""
memory_warn=""
disk_warn=""
overload_samples=""

info()  { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
ok()    { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

on_error() {
  error "安裝未完成（第 ${1} 行）。修正問題後可再次執行本安裝器。"
}
trap 'on_error "${LINENO}"' ERR

if [[ ${EUID} -ne 0 ]]; then
  error "請使用 sudo 執行：sudo bash install.sh"
  exit 1
fi

if [[ ! -t 0 &&
      "${VPS_SENTINEL_NONINTERACTIVE:-false}" != "true" ]]; then
  error "這是互動式安裝器，請直接在終端機執行，不要透過 pipe 傳入。"
  exit 1
fi

for required in vps_monitor.py node_contract.py legacy_adapter.py \
  requirements.txt vps-monitor.service; do
  if [[ ! -f "${SCRIPT_DIR}/${required}" ]]; then
    error "找不到 ${required}。請在完整的 vps-monitor 目錄中執行 install.sh。"
    exit 1
  fi
done

prompt() {
  local __result_var="$1" label="$2" default_value="${3-}" input
  if [[ -n "${default_value}" ]]; then
    read -r -p "${label} [${default_value}]：" input
    input="${input:-${default_value}}"
  else
    while [[ -z "${input:-}" ]]; do
      read -r -p "${label}：" input
    done
  fi
  printf -v "${__result_var}" '%s' "${input}"
}

prompt_secret() {
  local __result_var="$1" label="$2" input
  while [[ -z "${input:-}" ]]; do
    read -r -s -p "${label}：" input
    printf '\n'
  done
  printf -v "${__result_var}" '%s' "${input}"
}

prompt_yes_no() {
  local __result_var="$1" label="$2" default_value="$3" input hint
  if [[ "${default_value}" == "yes" ]]; then hint="Y/n"; else hint="y/N"; fi
  while true; do
    read -r -p "${label} [${hint}]：" input
    input="${input:-${default_value}}"
    case "${input,,}" in
      y|yes|是) printf -v "${__result_var}" 'true'; return ;;
      n|no|否)  printf -v "${__result_var}" 'false'; return ;;
      *) warn "請輸入 y 或 n。" ;;
    esac
  done
}

require_number() {
  local label="$1" value="$2"
  if [[ ! "${value}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    error "${label} 必須是數字，目前值為：${value}"
    exit 1
  fi
}

require_integer() {
  local label="$1" value="$2"
  if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
    error "${label} 必須是整數，目前值為：${value}"
    exit 1
  fi
}

require_percent() {
  local label="$1" value="$2"
  require_number "${label}" "${value}"
  if ! awk -v value="${value}" 'BEGIN { exit !(value >= 1 && value <= 100) }'; then
    error "${label} 必須介於 1 到 100，目前值為：${value}"
    exit 1
  fi
}

env_value() {
  local value="$1"
  if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
    error "設定值不可包含換行。"
    exit 1
  fi
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "${value}"
}

clear
printf '\033[1;35m'
cat <<'BANNER'
====================================================
 VPS Sentinel 中文安裝器
====================================================
BANNER
printf '\033[0m'
echo "此安裝器會安裝監控服務、建立 MQTT 設定並立即啟動。"
echo "VPS 不需要開放任何入站連接埠。"

if [[ -e "${ENV_FILE}" ]]; then
  prompt_yes_no reuse_config "偵測到既有設定，是否沿用並直接重新安裝" "yes"
  if [[ "${reuse_config}" == "true" ]]; then
    configure="false"
  else
    configure="true"
    backup="${ENV_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
    cp -a "${ENV_FILE}" "${backup}"
    ok "既有設定已備份至 ${backup}"
  fi
else
  configure="true"
fi

if [[ "${configure}" == "true" ]]; then
  info "步驟 1/4：MQTT 與 VPS 設定"
  prompt mqtt_host "MQTT Broker 位址（IP 或網域）"
  prompt_yes_no mqtt_tls "Broker 是否使用 TLS 加密" "no"
  if [[ "${mqtt_tls}" == "true" ]]; then
    prompt mqtt_port "MQTT 連接埠" "8883"
    read -r -p "自訂 CA 憑證路徑（直接 Enter 使用系統憑證）：" mqtt_ca_file
  else
    prompt mqtt_port "MQTT 連接埠" "1883"
    mqtt_ca_file=""
  fi
  prompt mqtt_username "MQTT 使用者名稱" "vps-monitor"
  prompt_secret mqtt_password "MQTT 密碼（輸入時不顯示）"

  default_id="$(hostname -s | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]/-/g')"
  prompt vps_id "VPS 識別 ID" "${default_id}"
  while [[ ! "${vps_id}" =~ ^[a-z0-9_-]+$ ]]; do
    warn "只能使用小寫英文字母、數字、底線與連字號。"
    prompt vps_id "VPS 識別 ID" "${default_id}"
  done
  prompt vps_name "Home Assistant 顯示名稱" "$(hostname -s)"
  prompt services "要監控的 systemd 服務，以空格分隔；不需要可留空" "ssh"

  info "步驟 2/4：資源模式與告警門檻"
  echo "  1) 極省資源：每 60 秒更新資源"
  echo "  2) 平衡模式：每 15 秒更新資源（推薦）"
  echo "  3) 即時監控：每 10 秒更新資源"
  while true; do
    read -r -p "請選擇模式 [2]：" resource_mode
    resource_mode="${resource_mode:-2}"
    case "${resource_mode}" in
      1)
        interval="60"
        health_interval="900"
        update_interval="86400"
        network_default="no"
        overload_default="5"
        mode_name="極省資源"
        break
        ;;
      2)
        interval="15"
        health_interval="300"
        update_interval="86400"
        network_default="no"
        overload_default="20"
        mode_name="平衡模式"
        break
        ;;
      3)
        interval="10"
        health_interval="60"
        update_interval="21600"
        network_default="yes"
        overload_default="30"
        mode_name="即時監控"
        break
        ;;
      *) warn "請輸入 1、2 或 3。" ;;
    esac
  done
  ok "已選擇：${mode_name}"
  prompt_yes_no monitor_network "是否監控即時網路上傳／下載速率" \
    "${network_default}"
  prompt cpu_warn "CPU 過載門檻（%）" "90"
  prompt memory_warn "記憶體過載門檻（%）" "90"
  prompt disk_warn "磁碟不足門檻（%）" "85"
  prompt overload_samples "連續幾次超標才告警" "${overload_default}"
  remote_actions=""
  prompt_yes_no remote_actions \
    "是否允許從 Home Assistant 執行安全更新與重新啟動" "no"

  require_integer "MQTT 連接埠" "${mqtt_port}"
  require_integer "回報間隔" "${interval}"
  require_percent "CPU 門檻" "${cpu_warn}"
  require_percent "記憶體門檻" "${memory_warn}"
  require_percent "磁碟門檻" "${disk_warn}"
  require_integer "連續超標次數" "${overload_samples}"
  if (( interval < 10 )); then
    error "回報間隔不可低於 10 秒。"
    exit 1
  fi

  umask 077
  {
    echo "# 由 VPS Sentinel 中文安裝器產生：$(date --iso-8601=seconds)"
    printf 'MQTT_HOST=%s\n' "$(env_value "${mqtt_host}")"
    printf 'MQTT_PORT=%s\n' "$(env_value "${mqtt_port}")"
    printf 'MQTT_USERNAME=%s\n' "$(env_value "${mqtt_username}")"
    printf 'MQTT_PASSWORD=%s\n' "$(env_value "${mqtt_password}")"
    printf 'MQTT_TLS=%s\n' "$(env_value "${mqtt_tls}")"
    printf 'MQTT_CA_FILE=%s\n' "$(env_value "${mqtt_ca_file}")"
    printf 'VPS_ID=%s\n' "$(env_value "${vps_id}")"
    printf 'VPS_NAME=%s\n' "$(env_value "${vps_name}")"
    printf 'PUBLISH_INTERVAL=%s\n' "$(env_value "${interval}")"
    printf 'HEALTH_CHECK_INTERVAL=%s\n' "$(env_value "${health_interval}")"
    printf 'UPDATE_CHECK_INTERVAL=%s\n' "$(env_value "${update_interval}")"
    printf 'MONITOR_NETWORK=%s\n' "$(env_value "${monitor_network}")"
    printf 'DISCOVERY_PREFIX=%s\n' '"homeassistant"'
    printf 'CPU_WARN_PERCENT=%s\n' "$(env_value "${cpu_warn}")"
    printf 'MEMORY_WARN_PERCENT=%s\n' "$(env_value "${memory_warn}")"
    printf 'DISK_WARN_PERCENT=%s\n' "$(env_value "${disk_warn}")"
    printf 'OVERLOAD_SAMPLES=%s\n' "$(env_value "${overload_samples}")"
    printf 'WATCH_SERVICES=%s\n' "$(env_value "${services}")"
    printf 'ALLOW_REMOTE_ACTIONS=%s\n' "$(env_value "${remote_actions}")"
    printf 'COMMAND_COOLDOWN=%s\n' '"300"'
    printf 'PUBLISH_V1_CONTRACT=%s\n' '"false"'
  } > "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
  ok "安全設定檔已建立（權限 600）"
else
  info "步驟 1/4、2/4：沿用既有設定"
fi

info "步驟 3/4：安裝程式與系統服務"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates unattended-upgrades

install -d -m 0755 "${INSTALL_DIR}"
install -m 0755 "${SCRIPT_DIR}/vps_monitor.py" "${INSTALL_DIR}/vps_monitor.py"
install -m 0644 "${SCRIPT_DIR}/node_contract.py" "${INSTALL_DIR}/node_contract.py"
install -m 0644 "${SCRIPT_DIR}/legacy_adapter.py" "${INSTALL_DIR}/legacy_adapter.py"
install -m 0644 "${SCRIPT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
if [[ -f "${SCRIPT_DIR}/../scripts/beta-evidence.py" ]]; then
  install -m 0755 "${SCRIPT_DIR}/../scripts/beta-evidence.py" \
    /usr/local/sbin/vps-sentinel-beta-evidence
fi
requirements_hash="$(sha256sum "${INSTALL_DIR}/requirements.txt" | awk '{print $1}')"
installed_hash="$(cat "${INSTALL_DIR}/.requirements.sha256" 2>/dev/null || true)"
if [[ ! -x "${INSTALL_DIR}/venv/bin/python" ||
      "${requirements_hash}" != "${installed_hash}" ]]; then
  info "Python 依賴有變更，正在建立執行環境"
  systemctl stop vps-monitor 2>/dev/null || true
  python3 -m venv --clear "${INSTALL_DIR}/venv"
  "${INSTALL_DIR}/venv/bin/pip" install --disable-pip-version-check \
    -r "${INSTALL_DIR}/requirements.txt"
  printf '%s\n' "${requirements_hash}" > \
    "${INSTALL_DIR}/.requirements.sha256"
else
  ok "Python 依賴未變更，略過重複安裝"
fi
install -m 0644 "${SCRIPT_DIR}/vps-monitor.service" "${SERVICE_FILE}"
systemctl daemon-reload
ok "程式與 systemd 服務已安裝"

info "步驟 4/4：啟動並檢查"
systemctl enable vps-monitor
systemctl restart vps-monitor
sleep 3
if systemctl is-active --quiet vps-monitor; then
  ok "vps-monitor 已啟動並設為開機自動執行"
  echo
  echo "接下來請到 Home Assistant → 設定 → 裝置與服務 → MQTT，"
  echo "確認 VPS 裝置與感測器已自動出現。"
  echo
  echo "常用指令："
  echo "  查看狀態：systemctl status vps-monitor"
  echo "  即時日誌：journalctl -u vps-monitor -f"
  echo "  重新設定：sudo bash ${SCRIPT_DIR}/install.sh"
else
  error "服務未能啟動，最近的日誌如下："
  journalctl -u vps-monitor -n 30 --no-pager || true
  exit 1
fi
