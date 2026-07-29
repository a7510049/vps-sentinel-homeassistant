#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENV_FILE="/etc/vps-monitor.env"
readonly HA_DIR="/opt/homeassistant"
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

record() {
  local level="$1" item="$2" detail="$3"
  RESULTS+=("${level}|${item}|${detail}")
  case "${level}" in
    PASS) ((PASS_COUNT += 1)); green "${item}：${detail}" ;;
    WARN) ((WARN_COUNT += 1)); yellow "${item}：${detail}" ;;
    FAIL) ((FAIL_COUNT += 1)); red "${item}：${detail}" ;;
  esac
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
  local recent
  service_check mosquitto "MQTT Broker"
  if command -v ss >/dev/null 2>&1 &&
     ss -lnt 2>/dev/null | awk '{print $4}' |
       grep -Eq '(^|:|\])1883$'; then
    record PASS "MQTT 連接埠" "1883 正在監聽"
  else
    record FAIL "MQTT 連接埠" "1883 未監聽"
  fi
  recent="$(journalctl -u vps-monitor --since '-30 minutes' --no-pager \
    2>/dev/null || true)"
  if grep -q 'MQTT 已連線' <<< "${recent}"; then
    record PASS "MQTT 連線" "監控程式近期曾成功連線"
  elif grep -Eq 'ConnectionRefused|MQTT 連線遭拒|Name or service not known' \
      <<< "${recent}"; then
    record FAIL "MQTT 連線" "近期日誌顯示連線失敗"
  else
    record WARN "MQTT 連線" "近期日誌沒有足夠資訊"
  fi
}

check_home_assistant() {
  local health
  if ! command -v docker >/dev/null 2>&1; then
    record WARN "Docker" "未安裝，略過 Home Assistant Container 檢查"
    return
  fi
  service_check docker "Docker"
  if ! docker inspect homeassistant >/dev/null 2>&1; then
    record WARN "Home Assistant" "找不到本專案管理的 Container"
    return
  fi
  health="$(docker inspect -f '{{.State.Status}}' homeassistant 2>/dev/null ||
    true)"
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
}

check_tailscale() {
  local state
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
}

run_checks() {
  RESULTS=()
  PASS_COUNT=0
  WARN_COUNT=0
  FAIL_COUNT=0
  check_environment
  heading "服務與連線"
  service_check vps-monitor "VPS Sentinel"
  check_mqtt
  check_home_assistant
  check_tailscale
  heading "主機資源"
  check_disk
  echo
  echo "檢查完成：${PASS_COUNT} 項正常、${WARN_COUNT} 項提醒、${FAIL_COUNT} 項異常"
}

safe_repairs() {
  local choice
  heading "安全修復"
  echo "  1) 修正監控設定檔權限"
  echo "  2) 重新載入並啟動 VPS Sentinel"
  echo "  3) 驗證後重新啟動 Home Assistant"
  echo "  4) 重新啟動 Mosquitto"
  echo "  0) 返回"
  read -r -p "請選擇：" choice
  case "${choice}" in
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
      if systemctl restart vps-monitor &&
         systemctl is-active --quiet vps-monitor; then
        green "VPS Sentinel 已重新啟動"
      else
        red "啟動失敗，請查看 journalctl -u vps-monitor -n 50"
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
      if systemctl restart mosquitto &&
         systemctl is-active --quiet mosquitto; then
        green "Mosquitto 已重新啟動"
      else
        red "Mosquitto 啟動失敗"
      fi
      ;;
    0) return ;;
    *) yellow "請輸入 0 到 4。" ;;
  esac
}

write_report() {
  local report version os_name kernel
  install -d -m 0700 "${REPORT_DIR}"
  report="${REPORT_DIR}/report-$(date +%Y%m%d-%H%M%S).txt"
  version="$(cat /opt/vps-monitor/.version 2>/dev/null || echo unknown)"
  os_name="$(sed -n 's/^PRETTY_NAME=//p' /etc/os-release 2>/dev/null |
    head -n 1 | tr -d '"' || true)"
  os_name="${os_name:-Linux}"
  kernel="$(uname -r)"
  {
    echo "VPS Sentinel 匿名診斷報告"
    echo "建立時間（UTC）：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "版本：${version}"
    echo "系統：${os_name}"
    echo "核心：${kernel}"
    echo "架構：$(uname -m)"
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
========================================================
 VPS Sentinel 健康檢查
========================================================
BANNER
  printf '\033[0m'
  run_checks
  echo
  echo "  1) 執行安全修復"
  echo "  2) 建立匿名診斷報告"
  echo "  3) 重新檢查"
  echo "  0) 返回"
  read -r -p "請選擇：" choice
  case "${choice}" in
    1) safe_repairs ;;
    2) write_report ;;
    3) continue ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 3。" ;;
  esac
  echo
  read -r -p "按 Enter 繼續……" _
done
