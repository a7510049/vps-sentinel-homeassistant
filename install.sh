#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_DIR
role=""
dry_run=false
assume_yes=false
config_file=""

usage() {
  cat <<'USAGE'
用法：sudo bash install.sh [--role combined|controller|agent] [--config bundle.json] [--dry-run] [--yes]

角色：
  combined    在本機安裝 Home Assistant、Broker、Controller 與 Agent
  controller  安裝 Home Assistant、Broker 與 Controller，不安裝本機 Agent
  agent       只安裝 Agent，連線到既有 Controller
USAGE
}

while (($#)); do
  case "$1" in
    --role)
      [[ $# -ge 2 ]] || { echo "--role 缺少值" >&2; exit 2; }
      role="$2"
      shift 2
      ;;
    --config)
      [[ $# -ge 2 ]] || { echo "--config 缺少檔案" >&2; exit 2; }
      config_file="$2"
      shift 2
      ;;
    --dry-run) dry_run=true; shift ;;
    --yes) assume_yes=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知參數：$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "${config_file}" && -z "${role}" ]]; then
  role="agent"
fi
if [[ -n "${config_file}" && "${role}" != "agent" ]]; then
  echo "--config 目前只適用於 agent 角色。" >&2
  exit 2
fi

if [[ -z "${role}" ]]; then
  [[ -t 0 ]] || {
    echo "非互動模式必須指定 --role。" >&2
    exit 2
  }
  echo "請選擇安裝角色："
  echo "  1) combined：Home Assistant + Controller + 本機 Agent（推薦首次安裝）"
  echo "  2) controller：Home Assistant + Controller"
  echo "  3) agent：只加入一台 VPS"
  read -r -p "選擇 [1]：" choice
  case "${choice:-1}" in
    1) role="combined" ;;
    2) role="controller" ;;
    3) role="agent" ;;
    *) echo "請選擇 1、2 或 3。" >&2; exit 2 ;;
  esac
fi

case "${role}" in
  combined)
    plan=(
      "檢查系統、Docker、Tailscale 與既有設定"
      "安裝或沿用 Home Assistant 與本機 Mosquitto"
      "安裝 Controller 並套用可回復的最小權限 ACL"
      "安裝本機 Agent 並保留 0.9.x 相容主題"
      "部署 Fleet Card，執行服務與 MQTT 驗證"
    )
    ;;
  controller)
    plan=(
      "檢查系統、Docker、Tailscale 與既有設定"
      "安裝或沿用 Home Assistant 與本機 Mosquitto"
      "略過本機 Agent"
      "安裝 Controller 並套用可回復的最小權限 ACL"
      "部署 Fleet Card，執行服務與 MQTT 驗證"
    )
    ;;
  agent)
    plan=(
      "檢查作業系統與既有 Agent 設定"
      "輸入既有 Controller MQTT 連線資料"
      "安裝或更新 Agent"
      "驗證服務啟動"
    )
    ;;
  *) echo "不支援的角色：${role}" >&2; exit 2 ;;
esac

echo
echo "執行計畫（${role}）："
for step in "${!plan[@]}"; do
  printf '  %d. %s\n' "$((step + 1))" "${plan[$step]}"
done

if [[ "${dry_run}" == "true" ]]; then
  echo
  echo "Dry-run 完成，未修改系統。"
  exit 0
fi

if [[ $EUID -ne 0 ]]; then
  echo "請使用 sudo 執行安裝。" >&2
  exit 1
fi

if [[ "${assume_yes}" != "true" ]]; then
  read -r -p "依照以上計畫繼續？[Y/n]：" confirm
  case "${confirm:-y}" in
    y|Y|yes|YES|是) ;;
    *) echo "已取消，未開始修改。"; exit 0 ;;
  esac
fi

case "${role}" in
  agent)
    if [[ -n "${config_file}" ]]; then
      python3 "${REPO_DIR}/controller/apply_agent_config.py"         "${config_file}"
      exit 0
    fi
    exec bash "${REPO_DIR}/vps-monitor/install.sh"
    ;;
  combined)
    VPS_SENTINEL_DEFER_SUMMARY=true \
      bash "${REPO_DIR}/setup.sh"
    python3 "${REPO_DIR}/controller/bootstrap.py"
    ;;
  controller)
    VPS_SENTINEL_SKIP_AGENT=true VPS_SENTINEL_DEFER_SUMMARY=true \
      bash "${REPO_DIR}/setup.sh"
    python3 "${REPO_DIR}/controller/bootstrap.py"
    ;;
esac

echo
echo "========================================================"
echo " VPS Sentinel ${role} 安裝完成"
echo "========================================================"
echo
echo "已完成：Home Assistant、Mosquitto ACL、Controller 與 Fleet Card 部署。"
if [[ "${role}" == "combined" ]]; then
  echo "本機 Agent 已切換為專用 node credential，並同時發布 0.9.x 相容與 v1 fleet 資料。"
else
  echo "請從 Controller 產生 Agent 註冊資料後加入 VPS。"
fi
echo
echo "Home Assistant 仍需完成："
echo "  1. 首次建立管理員"
echo "  2. 加入 MQTT 整合"
echo "  3. Fleet Card 已由標準 frontend 設定自動載入；客製 !include 結構才需依提示手動加入"
echo
echo "排錯：sudo journalctl -u vps-sentinel-controller -n 50 --no-pager"
