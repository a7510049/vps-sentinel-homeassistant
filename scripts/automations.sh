#!/usr/bin/env bash
set -Eeuo pipefail

readonly HA_DIR="/opt/homeassistant"
readonly BLUEPRINT_DIR="${HA_DIR}/config/blueprints/automation/vps_sentinel"
readonly SOURCE_DIR="/opt/vps-monitor/blueprints"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel-automations"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "模板管理只能在互動式終端機執行。"
  exit 1
fi

install_blueprints() {
  local file
  if [[ ! -d "${SOURCE_DIR}" ]]; then
    red "找不到內建模板，請先更新 VPS Sentinel。"
    return 1
  fi
  install -d -m 0755 "${BLUEPRINT_DIR}"
  for file in "${SOURCE_DIR}"/*.yaml; do
    [[ -f "${file}" ]] || continue
    install -m 0644 "${file}" "${BLUEPRINT_DIR}/$(basename "${file}")"
  done
  green "Home Assistant 自動化模板已安裝"
  echo
  echo "接下來請到 Home Assistant："
  echo "設定 → 自動化與場景 → 藍圖"
  echo "選擇「VPS Sentinel」模板並建立自動化。"
  echo
  echo "模板不會自動取得通知權限；建立時由你選擇手機或其他通知動作。"
}

show_status() {
  echo
  if [[ -f "${BLUEPRINT_DIR}/problem-notification.yaml" &&
        -f "${BLUEPRINT_DIR}/offline-notification.yaml" ]]; then
    green "推薦通知模板已安裝"
  else
    yellow "推薦通知模板尚未完整安裝"
  fi
  if [[ -f "${BLUEPRINT_DIR}/daily-summary.yaml" ]]; then
    green "每日摘要模板已安裝"
  else
    yellow "每日摘要模板尚未安裝"
  fi
}

remove_blueprints() {
  local confirmation
  yellow "這只會移除 VPS Sentinel 的藍圖檔案。"
  echo "已使用藍圖建立的自動化會留在 Home Assistant，請在 UI 中自行刪除。"
  read -r -p "若要繼續，請輸入：移除模板 > " confirmation
  [[ "${confirmation}" == "移除模板" ]] || {
    echo "已取消。"
    return
  }
  case "${BLUEPRINT_DIR}" in
    "${HA_DIR}/config/blueprints/automation/vps_sentinel")
      rm -rf -- "${BLUEPRINT_DIR}"
      ;;
    *) red "模板路徑驗證失敗"; return 1 ;;
  esac
  green "VPS Sentinel 藍圖檔案已移除"
}

while true; do
  clear
  printf '\033[1;35m'
  cat <<'BANNER'
╭────────────────────────────────────────╮
│  🔔 Home Assistant 通知與自動化        │
╰────────────────────────────────────────╯
BANNER
  printf '\033[0m'
  echo "  1. 安裝或更新推薦模板"
  echo "  2. 查看模板狀態"
  echo "  3. 移除模板檔案"
  echo "  0. 返回上一層"
  read -r -p "請選擇 [0]：" choice
  case "${choice:-0}" in
    1) install_blueprints ;;
    2) show_status ;;
    3) remove_blueprints ;;
    0) exit 0 ;;
    *) yellow "請輸入 0 到 3。" ;;
  esac
  echo
  read -r -p "按 Enter 返回模板管理……" _
done
