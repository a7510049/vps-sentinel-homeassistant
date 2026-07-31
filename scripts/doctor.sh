#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/vps-monitor.env"
readonly HA_DIR="/opt/homeassistant"
readonly HA_CONFIG="${HA_DIR}/config/configuration.yaml"
readonly CARD_SOURCE="/opt/vps-monitor/vps-sentinel-apple-card.js"
readonly CARD_TARGET="${HA_DIR}/config/www/vps-sentinel-apple-card.js"
readonly MQTT_PASSWD="/etc/mosquitto/passwd"
readonly CREDENTIALS_FILE="/root/vps-homeassistant-credentials.txt"
readonly IP_BANS="${HA_DIR}/config/ip_bans.yaml"
readonly REPORT_DIR="/root/vps-sentinel-reports"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }
heading(){ printf '\n\033[1;36m%s\033[0m\n' "$*"; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel-doctor"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "診斷工具只能在互動式終端機執行。"
  exit 1
fi

declare -a RESULTS=()
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
MQTT_PROBE_RESULT="未檢查"

record() {
  local level="$1" item="$2" detail="$3"
  RESULTS+=("${level}|${item}|${detail}")
  case "${level}" in
    PASS) ((PASS_COUNT += 1)); green "${item}：${detail}" ;;
    WARN) ((WARN_COUNT += 1)); yellow "${item}：${detail}" ;;
    FAIL) ((FAIL_COUNT += 1)); red "${item}：${detail}" ;;
  esac
}

read_env() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "${ENV_FILE}" 2>/dev/null | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

service_check() {
  local service="$1" label="$2"
  if ! systemctl list-unit-files "${service}.service" --no-legend \
      2>/dev/null | grep -q "^${service}.service"; then
    record WARN "${label}" "未安裝"
  elif systemctl is-active --quiet "${service}"; then
    record PASS "${label}" "運作正常"
  else
    record FAIL "${label}" "服務未運行"
  fi
}

mqtt_probe() {
  local host port username password vps_id output
  host="$(read_env MQTT_HOST)"
  port="$(read_env MQTT_PORT)"
  username="$(read_env MQTT_USERNAME)"
  password="$(read_env MQTT_PASSWORD)"
  vps_id="$(read_env VPS_ID)"
  if [[ -z "${host}" || -z "${username}" || -z "${vps_id}" ]]; then
    MQTT_PROBE_RESULT="設定不完整"
    return 1
  fi
  if output="$(timeout 12 mosquitto_sub \
      -h "${host}" -p "${port:-1883}" \
      -u "${username}" -P "${password}" \
      -t "vps/${vps_id}/online" -C 1 2>&1)" &&
     grep -qx 'ON' <<< "${output}"; then
    MQTT_PROBE_RESULT="認證與資料正常"
    return 0
  fi
  if grep -qiE 'not authorized|connection refused|拒絕' <<< "${output}"; then
    MQTT_PROBE_RESULT="認證失敗"
  else
    MQTT_PROBE_RESULT="未收到在線資料"
  fi
  return 1
}

check_environment() {
  local mode owner
  heading "核心環境"
  if [[ -f "${ENV_FILE}" ]]; then
    mode="$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || true)"
    owner="$(stat -c '%U:%G' "${ENV_FILE}" 2>/dev/null || true)"
    if [[ "${mode}" == "600" && "${owner}" == "root:root" ]]; then
      record PASS "監控設定權限" "root 專用（600）"
    else
      record FAIL "監控設定權限" "${owner:-未知}／${mode:-未知}，建議修復"
    fi
  else
    record FAIL "監控設定" "找不到 ${ENV_FILE}"
  fi

  if [[ -x /opt/vps-monitor/venv/bin/python &&
        -f /opt/vps-monitor/vps_monitor.py ]]; then
    if /opt/vps-monitor/venv/bin/python -m py_compile \
        /opt/vps-monitor/vps_monitor.py 2>/dev/null; then
      record PASS "監控程式" "Python 語法正常"
    else
      record FAIL "監控程式" "Python 語法檢查失敗"
    fi
  else
    record FAIL "監控程式" "安裝內容不完整"
  fi
}

check_disk() {
  local used available
  used="$(df -P / | awk 'NR == 2 {gsub("%","",$5); print $5}')"
  available="$(df -hP / | awk 'NR == 2 {print $4}')"
  if [[ "${used:-100}" -ge 95 ]]; then
    record FAIL "根目錄空間" "已使用 ${used}%（剩餘 ${available:-未知}）"
  elif [[ "${used:-100}" -ge 85 ]]; then
    record WARN "根目錄空間" "已使用 ${used}%（剩餘 ${available:-未知}）"
  else
    record PASS "根目錄空間" "已使用 ${used}%（剩餘 ${available:-未知}）"
  fi
}

check_mqtt() {
  service_check mosquitto "MQTT Broker"
  if command -v ss >/dev/null 2>&1 &&
     ss -lnt 2>/dev/null | awk '{print $4}' |
       grep -Eq '127\.0\.0\.1:1883$'; then
    record PASS "MQTT 連接埠" "只在本機 127.0.0.1:1883 監聽"
  else
    record FAIL "MQTT 連接埠" "未偵測到本機限定的 1883 監聽"
  fi
  if command -v mosquitto_sub >/dev/null 2>&1 && mqtt_probe; then
    record PASS "MQTT 實際登入" "${MQTT_PROBE_RESULT}"
  else
    record FAIL "MQTT 實際登入" "${MQTT_PROBE_RESULT}"
  fi
}

check_home_assistant() {
  local health compose_name
  if ! command -v docker >/dev/null 2>&1; then
    record WARN "Docker" "未安裝，略過 Home Assistant Container 檢查"
    return
  fi
  service_check docker "Docker"
  if [[ -f "${HA_DIR}/compose.yaml" ]]; then
    compose_name="compose.yaml"
  elif [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    compose_name="docker-compose.yml（舊格式）"
  else
    compose_name="找不到"
  fi
  if [[ "${compose_name}" == "找不到" ]]; then
    record FAIL "Compose 設定" "找不到 Home Assistant Compose 檔"
  else
    record PASS "Compose 設定" "${compose_name}"
  fi
  if ! docker inspect homeassistant >/dev/null 2>&1; then
    record WARN "Home Assistant" "找不到本專案管理的 Container"
    return
  fi
  health="$(docker inspect -f '{{.State.Status}}' homeassistant 2>/dev/null || true)"
  if [[ "${health}" == "running" ]]; then
    record PASS "Home Assistant Container" "運作正常"
  else
    record FAIL "Home Assistant Container" "狀態：${health:-未知}"
  fi
  if docker exec homeassistant python -m homeassistant --script check_config \
      --config /config >/dev/null 2>&1; then
    record PASS "Home Assistant 設定" "語法正常"
  else
    record FAIL "Home Assistant 設定" "驗證失敗"
  fi
  if curl -fsS --max-time 3 http://127.0.0.1:8123/ >/dev/null 2>&1; then
    record PASS "Home Assistant 網頁" "本機連線正常"
  else
    record FAIL "Home Assistant 網頁" "本機 8123 無法連線"
  fi

  if grep -q '^[[:space:]]*use_x_forwarded_for:[[:space:]]*true' "${HA_CONFIG}" \
      2>/dev/null &&
     grep -q '^[[:space:]]*-[[:space:]]*127\.0\.0\.1[[:space:]]*$' \
      "${HA_CONFIG}" 2>/dev/null; then
    record PASS "反向代理設定" "已信任本機 Tailscale Serve 代理"
  else
    record WARN "反向代理設定" "缺少 use_x_forwarded_for 或 trusted_proxies"
  fi
  if [[ -s "${IP_BANS}" ]]; then
    record WARN "登入封鎖" "ip_bans.yaml 目前有封鎖紀錄"
  else
    record PASS "登入封鎖" "沒有持續的 IP 封鎖紀錄"
  fi
}

check_tailscale() {
  local state serve
  if ! command -v tailscale >/dev/null 2>&1; then
    record WARN "Tailscale" "未安裝"
    return
  fi
  state="$(tailscale status --json 2>/dev/null |
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState",""))' \
    2>/dev/null || true)"
  if [[ "${state}" == "Running" ]]; then
    record PASS "Tailscale" "已連線"
  else
    record WARN "Tailscale" "狀態：${state:-無法讀取}"
  fi
  serve="$(tailscale serve status 2>/dev/null || true)"
  if grep -q '127.0.0.1:8123' <<< "${serve}"; then
    record PASS "Tailscale Serve" "已代理到 Home Assistant"
  else
    record WARN "Tailscale Serve" "未偵測到 127.0.0.1:8123"
  fi
}

card_version() {
  sed -n 's/^const CARD_VERSION = "\([^"]*\)";.*/\1/p' "$1" 2>/dev/null |
    head -n 1
}

check_apple_card() {
  local installed source_version
  installed="$(cat /opt/vps-monitor/.version 2>/dev/null || true)"
  source_version="$(card_version "${CARD_SOURCE}")"
  if [[ -f "${CARD_SOURCE}" && "${source_version}" == "${installed}" ]]; then
    record PASS "Apple 卡片來源" "版本 ${source_version}"
  else
    record WARN "Apple 卡片來源" "專案版本與卡片版本不同步"
  fi
  if [[ -f "${CARD_TARGET}" ]] && cmp -s "${CARD_SOURCE}" "${CARD_TARGET}"; then
    record PASS "Apple 卡片資源" "Home Assistant 已使用最新檔案"
  else
    record WARN "Apple 卡片資源" "需要執行 sudo vps-sentinel apple"
  fi
}

run_checks() {
  RESULTS=()
  PASS_COUNT=0
  WARN_COUNT=0
  FAIL_COUNT=0
  MQTT_PROBE_RESULT="未檢查"
  check_environment
  heading "服務與連線"
  service_check vps-monitor "VPS Sentinel"
  check_mqtt
  check_home_assistant
  check_tailscale
  check_apple_card
  heading "主機資源"
  check_disk
  echo
  echo "檢查完成：${PASS_COUNT} 項正常、${WARN_COUNT} 項提醒、${FAIL_COUNT} 項異常"
}

save_monitor_credential() {
  local password="$1"
  python3 - "${CREDENTIALS_FILE}" "${password}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
password = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
    "VPS Monitor 安裝憑證",
]
lines = [
    line for line in lines
    if not line.startswith("VPS Monitor MQTT 使用者：")
    and not line.startswith("VPS Monitor MQTT 密碼：")
]
while lines and not lines[-1].strip():
    lines.pop()
lines.extend([
    "",
    "VPS Monitor MQTT 使用者：vps-monitor",
    f"VPS Monitor MQTT 密碼：{password}",
])
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  chmod 0600 "${CREDENTIALS_FILE}"
}

reset_monitor_mqtt_password() {
  local new_password backup_passwd backup_env answer
  [[ -f "${MQTT_PASSWD}" && -f "${ENV_FILE}" ]] || {
    red "找不到 MQTT 密碼檔或監控設定檔"
    return 1
  }
  read -r -p "確定重新同步 vps-monitor 的 MQTT 密碼嗎？[y/N]：" answer
  [[ "${answer,,}" =~ ^(y|yes|是)$ ]] || return
  new_password="$(openssl rand -hex 24)"
  backup_passwd="${MQTT_PASSWD}.backup.$(date +%Y%m%d-%H%M%S)"
  backup_env="${ENV_FILE}.backup.$(date +%Y%m%d-%H%M%S)"
  cp -a "${MQTT_PASSWD}" "${backup_passwd}"
  cp -a "${ENV_FILE}" "${backup_env}"
  if ! mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor "${new_password}"; then
    red "無法更新 Mosquitto 密碼"
    return 1
  fi
  python3 - "${ENV_FILE}" "${new_password}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
password = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
replacement = f'MQTT_PASSWORD="{password}"'
for index, line in enumerate(lines):
    if line.startswith("MQTT_PASSWORD="):
        lines[index] = replacement
        break
else:
    lines.append(replacement)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  chown root:mosquitto "${MQTT_PASSWD}"
  chmod 0640 "${MQTT_PASSWD}"
  chown root:root "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
  if systemctl restart mosquitto && systemctl restart vps-monitor &&
     sleep 5 && mqtt_probe; then
    save_monitor_credential "${new_password}"
    rm -f -- "${backup_passwd}" "${backup_env}"
    green "VPS Monitor MQTT 密碼已同步，實際登入成功"
    green "新密碼已保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
    return
  fi
  cp -a "${backup_passwd}" "${MQTT_PASSWD}"
  cp -a "${backup_env}" "${ENV_FILE}"
  chown root:mosquitto "${MQTT_PASSWD}"
  chmod 0640 "${MQTT_PASSWD}"
  systemctl restart mosquitto || true
  systemctl restart vps-monitor || true
  red "同步後驗證失敗，已回復原設定"
  return 1
}

clear_ip_bans() {
  local confirmation
  yellow "請先完全關閉正在反覆登入失敗的 Home Assistant App。"
  read -r -p "若要清除封鎖，請輸入：清除封鎖 > " confirmation
  [[ "${confirmation}" == "清除封鎖" ]] || return
  if [[ -f "${IP_BANS}" ]]; then
    mv "${IP_BANS}" "${IP_BANS}.backup.$(date +%Y%m%d-%H%M%S)"
  fi
  (cd "${HA_DIR}" && docker compose restart homeassistant)
  green "Home Assistant IP 封鎖已清除"
}

safe_repairs() {
  local choice
  heading "安全修復"
  echo "  1. 修正監控設定檔權限"
  echo "  2. 重新載入並啟動 VPS Sentinel"
  echo "  3. 驗證後重新啟動 Home Assistant"
  echo "  4. 重新啟動 Mosquitto"
  echo "  5. 同步 VPS Monitor MQTT 密碼"
  echo "  6. 同步 Apple 卡片前端檔案"
  echo "  7. 清除 Home Assistant IP 封鎖"
  echo "  0. 返回上一層"
  read -r -p "請選擇 [0]：" choice
  case "${choice:-0}" in
    1)
      if [[ -f "${ENV_FILE}" ]]; then
        chown root:root "${ENV_FILE}"
        chmod 0600 "${ENV_FILE}"
        green "監控設定檔權限已修正"
      else
        red "找不到監控設定檔"
      fi
      ;;
    2)
      systemctl daemon-reload
      if systemctl restart vps-monitor && sleep 3 && mqtt_probe; then
        green "VPS Sentinel 已重新啟動，MQTT 資料正常"
      else
        red "啟動或 MQTT 驗證失敗"
        journalctl -u vps-monitor -n 50 --no-pager || true
      fi
      ;;
    3)
      if docker exec homeassistant python -m homeassistant \
          --script check_config --config /config; then
        (cd "${HA_DIR}" && docker compose restart homeassistant)
        green "Home Assistant 已通過驗證並重新啟動"
      else
        red "設定驗證失敗，未重新啟動 Home Assistant"
      fi
      ;;
    4)
      if systemctl restart mosquitto && systemctl is-active --quiet mosquitto; then
        green "Mosquitto 已重新啟動"
      else
        red "Mosquitto 啟動失敗"
      fi
      ;;
    5) reset_monitor_mqtt_password ;;
    6)
      install -d -m 0755 "$(dirname "${CARD_TARGET}")"
      install -m 0644 "${CARD_SOURCE}" "${CARD_TARGET}"
      green "Apple 卡片已同步；不需要重新啟動 Home Assistant"
      ;;
    7) clear_ip_bans ;;
    0) return ;;
    *) yellow "請輸入 0 到 7。" ;;
  esac
}

write_report() {
  local report version os_name kernel compose card
  install -d -m 0700 "${REPORT_DIR}"
  report="${REPORT_DIR}/report-$(date +%Y%m%d-%H%M%S).txt"
  version="$(cat /opt/vps-monitor/.version 2>/dev/null || echo unknown)"
  os_name="$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release 2>/dev/null |
    head -n 1 | tr -d '"' || true)"
  os_name="${os_name:-Linux}"
  kernel="$(uname -r)"
  if [[ -f "${HA_DIR}/compose.yaml" ]]; then
    compose="compose.yaml"
  elif [[ -f "${HA_DIR}/docker-compose.yml" ]]; then
    compose="docker-compose.yml"
  else
    compose="missing"
  fi
  card="$(card_version "${CARD_SOURCE}")"
  {
    echo "VPS Sentinel 匿名診斷報告"
    echo "建立時間（UTC）：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "版本：${version}"
    echo "系統：${os_name}"
    echo "核心：${kernel}"
    echo "架構：$(uname -m)"
    echo "Compose：${compose}"
    echo "Apple 卡片：${card:-unknown}"
    echo "MQTT 驗證：${MQTT_PROBE_RESULT}"
    echo
    printf '%-6s | %-28s | %s\n' "結果" "項目" "說明"
    printf '%s\n' "----------------------------------------------------------------------"
    for result in "${RESULTS[@]}"; do
      IFS='|' read -r level item detail <<< "${result}"
      printf '%-6s | %-28s | %s\n' "${level}" "${item}" "${detail}"
    done
  } > "${report}"
  chmod 0600 "${report}"
  green "匿名診斷報告已建立：${report}"
  echo "報告不包含 MQTT 密碼、Token、IP 位址、VPS 名稱或完整日誌。"
}

while true; do
  clear
  printf '\033[1;35m'
  cat <<'BANNER'
╭────────────────────────────────────────╮
│  🩺 VPS Sentinel 健康檢查              │
╰────────────────────────────────────────╯
BANNER
  printf '\033[0m'
  run_checks
  echo
  echo "接下來可以："
  echo
  echo "  1. 執行安全修復"
  echo "  2. 建立匿名診斷報告"
  echo "  3. 重新檢查"
  echo "  0. 返回上一層"
  read -r -p "請選擇 [0]：" choice
  case "${choice:-0}" in
    1) safe_repairs ;;
    2) write_report ;;
    3) continue ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 3。" ;;
  esac
  echo
  read -r -p "按 Enter 返回健康檢查……" _
done
