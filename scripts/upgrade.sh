#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPOSITORY="a7510049/vps-sentinel-homeassistant"
readonly INSTALL_DIR="/opt/vps-monitor"
readonly BACKUP_ROOT="/opt/vps-monitor-backups"
readonly SERVICE_FILE="/etc/systemd/system/vps-monitor.service"
readonly CARD_TARGET="/opt/homeassistant/config/www/vps-sentinel-apple-card.js"
readonly MANAGE_COMMAND="/usr/local/sbin/vps-sentinel"
readonly UPDATE_COMMAND="/usr/local/sbin/vps-sentinel-update"
readonly UNINSTALL_COMMAND="/usr/local/sbin/vps-sentinel-uninstall"
readonly UPGRADE_COMMAND="/usr/local/sbin/vps-sentinel-upgrade"
readonly DOCTOR_COMMAND="/usr/local/sbin/vps-sentinel-doctor"
readonly BACKUP_COMMAND="/usr/local/sbin/vps-sentinel-backup"
readonly AUTOMATIONS_COMMAND="/usr/local/sbin/vps-sentinel-automations"
readonly APPLE_COMMAND="/usr/local/sbin/vps-sentinel-apple"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo vps-sentinel-upgrade"
  exit 1
fi
if [[ ! -t 0 ]]; then
  red "升級工具只能在互動式終端機執行。"
  exit 1
fi
for command in curl tar python3 mosquitto_sub timeout; do
  command -v "${command}" >/dev/null 2>&1 || {
    red "缺少必要指令：${command}"
    exit 1
  }
done
available_kb="$(df -Pk /opt | awk 'NR == 2 {print $4}')"
if [[ "${available_kb:-0}" -lt 204800 ]]; then
  red "可用空間低於 200 MiB，為避免升級中斷，請先清理磁碟。"
  exit 1
fi
if [[ ! -f /etc/vps-monitor.env ||
      ! -x "${INSTALL_DIR}/venv/bin/python" ]]; then
  red "目前安裝不完整，請先執行 sudo vps-sentinel-doctor。"
  exit 1
fi

read_env() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" /etc/vps-monitor.env | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

mqtt_probe() {
  local host port username password vps_id
  host="$(read_env MQTT_HOST)"
  port="$(read_env MQTT_PORT)"
  username="$(read_env MQTT_USERNAME)"
  password="$(read_env MQTT_PASSWORD)"
  vps_id="$(read_env VPS_ID)"
  [[ -n "${host}" && -n "${username}" && -n "${vps_id}" ]] || return 1
  timeout 15 mosquitto_sub \
    -h "${host}" -p "${port:-1883}" \
    -u "${username}" -P "${password}" \
    -t "vps/${vps_id}/online" -C 1 2>/dev/null |
    grep -qx 'ON'
}

wait_for_monitor_mqtt() {
  local started_at="$1" _
  for _ in {1..15}; do
    if journalctl -u vps-monitor --since "${started_at}" --no-pager \
        2>/dev/null | grep -q 'MQTT 已連線' && mqtt_probe; then
      return 0
    fi
    sleep 2
  done
  return 1
}

printf '\033[1;35m'
cat <<'BANNER'
╭────────────────────────────────────────╮
│  🔄 VPS Sentinel 安全更新              │
╰────────────────────────────────────────╯
BANNER
printf '\033[0m'
echo "更新前會檢查版本與檔案，服務或 MQTT 驗證失敗時自動回復。"
echo

temporary="$(mktemp -d)"
cleanup() {
  rm -rf -- "${temporary}"
}
trap cleanup EXIT

current_version="$(cat "${INSTALL_DIR}/.version" 2>/dev/null || echo "0.2.x")"
echo "目前版本：${current_version}"
echo "正在查詢最新穩定版本……"
latest_url="$(curl -fsSIL -o /dev/null -w '%{url_effective}' \
  "https://github.com/${REPOSITORY}/releases/latest")"
latest_tag="${latest_url##*/}"
if [[ ! "${latest_tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  red "無法辨識最新版本：${latest_tag}"
  exit 1
fi
latest_version="${latest_tag#v}"
echo "最新版本：${latest_version}"
if [[ "${current_version}" == "${latest_version}" ]]; then
  green "目前已是最新版本"
  exit 0
fi

read -r -p "是否升級至 ${latest_version} [y/N]：" answer
case "${answer,,}" in
  y|yes|是) ;;
  *) echo "已取消升級。"; exit 0 ;;
esac

archive="${temporary}/source.tar.gz"
curl -fL --retry 3 --proto '=https' --tlsv1.2 \
  "https://github.com/${REPOSITORY}/archive/refs/tags/${latest_tag}.tar.gz" \
  -o "${archive}"
tar -xzf "${archive}" -C "${temporary}"
source_dir="$(find "${temporary}" -mindepth 1 -maxdepth 1 -type d \
  -name 'vps-sentinel-homeassistant-*' -print -quit)"
if [[ -z "${source_dir}" ]]; then
  red "下載內容不完整，已取消升級。"
  exit 1
fi
for file in VERSION scripts/manage.sh scripts/update.sh scripts/uninstall.sh \
  scripts/upgrade.sh scripts/doctor.sh scripts/backup.sh \
  scripts/automations.sh scripts/apple-dashboard.sh \
  vps-monitor/vps_monitor.py vps-monitor/node_contract.py \
  vps-monitor/legacy_adapter.py vps-monitor/requirements.txt \
  vps-monitor/vps-monitor.service \
  home-assistant/blueprints/problem-notification.yaml \
  home-assistant/blueprints/offline-notification.yaml \
  home-assistant/blueprints/daily-summary.yaml \
  home-assistant/www/vps-sentinel-apple-card.js; do
  [[ -f "${source_dir}/${file}" ]] || {
    red "下載內容缺少 ${file}，已取消升級。"
    exit 1
  }
done
downloaded_version="$(tr -d '[:space:]' < "${source_dir}/VERSION")"
if [[ "${downloaded_version}" != "${latest_version}" ]]; then
  red "版本檔與 Release 標籤不一致，已取消升級。"
  exit 1
fi
card_version="$(sed -n 's/^const CARD_VERSION = "\([^"]*\)";.*/\1/p' \
  "${source_dir}/home-assistant/www/vps-sentinel-apple-card.js" | head -n 1)"
if [[ "${card_version}" != "${latest_version}" ]]; then
  red "Apple 卡片版本 ${card_version:-未知} 與 Release 不一致。"
  exit 1
fi
bash -n "${source_dir}/scripts/"*.sh
python3 -m py_compile \
  "${source_dir}/vps-monitor/vps_monitor.py" \
  "${source_dir}/vps-monitor/node_contract.py" \
  "${source_dir}/vps-monitor/legacy_adapter.py"
green "下載內容、版本與基本語法檢查完成"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup="${BACKUP_ROOT}/${timestamp}"
install -d -m 0700 "${backup}"
cp -a "${INSTALL_DIR}/vps_monitor.py" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/node_contract.py" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/legacy_adapter.py" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/requirements.txt" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/.requirements.sha256" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/.version" "${backup}/" 2>/dev/null || true
cp -a "${INSTALL_DIR}/vps-sentinel-apple-card.js" \
  "${backup}/" 2>/dev/null || true
if [[ -f "${CARD_TARGET}" ]]; then
  cp -a "${CARD_TARGET}" "${backup}/homeassistant-card.js"
fi
cp -a "${SERVICE_FILE}" "${backup}/vps-monitor.service" 2>/dev/null || true
for file in "${MANAGE_COMMAND}" "${UPDATE_COMMAND}" \
  "${UNINSTALL_COMMAND}" "${UPGRADE_COMMAND}" "${DOCTOR_COMMAND}" \
  "${BACKUP_COMMAND}" "${AUTOMATIONS_COMMAND}" "${APPLE_COMMAND}"; do
  [[ -e "${file}" ]] && cp -a "${file}" "${backup}/$(basename "${file}")"
done
[[ ! -d "${INSTALL_DIR}/blueprints" ]] ||
  cp -a "${INSTALL_DIR}/blueprints" "${backup}/"
green "舊版本已備份：${backup}"

rollback() {
  trap - ERR
  red "新版本未能通過完整驗證，正在回復 ${current_version}。"
  install -m 0755 "${backup}/vps_monitor.py" \
    "${INSTALL_DIR}/vps_monitor.py"
  for module in node_contract.py legacy_adapter.py; do
    if [[ -f "${backup}/${module}" ]]; then
      install -m 0644 "${backup}/${module}" "${INSTALL_DIR}/${module}"
    else
      rm -f -- "${INSTALL_DIR}/${module}"
    fi
  done
  install -m 0644 "${backup}/requirements.txt" \
    "${INSTALL_DIR}/requirements.txt"
  [[ ! -f "${backup}/.requirements.sha256" ]] ||
    install -m 0644 "${backup}/.requirements.sha256" \
      "${INSTALL_DIR}/.requirements.sha256"
  [[ ! -f "${backup}/.version" ]] ||
    install -m 0644 "${backup}/.version" "${INSTALL_DIR}/.version"
  if [[ -f "${backup}/vps-sentinel-apple-card.js" ]]; then
    install -m 0644 "${backup}/vps-sentinel-apple-card.js" \
      "${INSTALL_DIR}/vps-sentinel-apple-card.js"
  else
    rm -f -- "${INSTALL_DIR}/vps-sentinel-apple-card.js"
  fi
  if [[ -f "${backup}/homeassistant-card.js" ]]; then
    install -d -m 0755 "$(dirname "${CARD_TARGET}")"
    install -m 0644 "${backup}/homeassistant-card.js" "${CARD_TARGET}"
  else
    rm -f -- "${CARD_TARGET}"
  fi
  [[ ! -f "${backup}/vps-monitor.service" ]] ||
    install -m 0644 "${backup}/vps-monitor.service" "${SERVICE_FILE}"
  for name in vps-sentinel vps-sentinel-update vps-sentinel-uninstall \
    vps-sentinel-upgrade vps-sentinel-doctor vps-sentinel-backup \
    vps-sentinel-automations vps-sentinel-apple; do
    if [[ -f "${backup}/${name}" ]]; then
      install -m 0755 "${backup}/${name}" "/usr/local/sbin/${name}"
    else
      rm -f -- "/usr/local/sbin/${name}"
    fi
  done
  rm -rf -- "${INSTALL_DIR}/blueprints"
  [[ ! -d "${backup}/blueprints" ]] ||
    cp -a "${backup}/blueprints" "${INSTALL_DIR}/"
  "${INSTALL_DIR}/venv/bin/pip" install --disable-pip-version-check \
    -r "${INSTALL_DIR}/requirements.txt" >/dev/null
  systemctl daemon-reload
  systemctl restart vps-monitor || true
}

upgrade_started=false
on_upgrade_error() {
  local line="$1"
  trap - ERR
  if [[ "${upgrade_started}" == "true" ]]; then
    rollback
  fi
  red "升級在第 ${line} 行中斷。"
  exit 1
}
trap 'on_upgrade_error "${LINENO}"' ERR

upgrade_started=true
systemctl stop vps-monitor
install -m 0755 "${source_dir}/vps-monitor/vps_monitor.py" \
  "${INSTALL_DIR}/vps_monitor.py"
install -m 0644 "${source_dir}/vps-monitor/node_contract.py" \
  "${INSTALL_DIR}/node_contract.py"
install -m 0644 "${source_dir}/vps-monitor/legacy_adapter.py" \
  "${INSTALL_DIR}/legacy_adapter.py"
install -m 0644 "${source_dir}/vps-monitor/requirements.txt" \
  "${INSTALL_DIR}/requirements.txt"
requirements_hash="$(sha256sum "${INSTALL_DIR}/requirements.txt" |
  awk '{print $1}')"
installed_hash="$(cat "${INSTALL_DIR}/.requirements.sha256" 2>/dev/null || true)"
if [[ "${requirements_hash}" != "${installed_hash}" ]]; then
  "${INSTALL_DIR}/venv/bin/pip" install --disable-pip-version-check \
    -r "${INSTALL_DIR}/requirements.txt"
  printf '%s\n' "${requirements_hash}" > \
    "${INSTALL_DIR}/.requirements.sha256"
fi
install -m 0644 "${source_dir}/vps-monitor/vps-monitor.service" \
  "${SERVICE_FILE}"
install -m 0755 "${source_dir}/scripts/manage.sh" "${MANAGE_COMMAND}"
install -m 0755 "${source_dir}/scripts/update.sh" "${UPDATE_COMMAND}"
install -m 0755 "${source_dir}/scripts/uninstall.sh" "${UNINSTALL_COMMAND}"
install -m 0755 "${source_dir}/scripts/upgrade.sh" "${UPGRADE_COMMAND}"
install -m 0755 "${source_dir}/scripts/doctor.sh" "${DOCTOR_COMMAND}"
install -m 0755 "${source_dir}/scripts/backup.sh" "${BACKUP_COMMAND}"
install -m 0755 "${source_dir}/scripts/automations.sh" \
  "${AUTOMATIONS_COMMAND}"
install -m 0755 "${source_dir}/scripts/apple-dashboard.sh" "${APPLE_COMMAND}"
install -m 0644 \
  "${source_dir}/home-assistant/www/vps-sentinel-apple-card.js" \
  "${INSTALL_DIR}/vps-sentinel-apple-card.js"
if [[ -f "${CARD_TARGET}" ]]; then
  install -d -m 0755 "$(dirname "${CARD_TARGET}")"
  install -m 0644 "${INSTALL_DIR}/vps-sentinel-apple-card.js" \
    "${CARD_TARGET}"
fi
install -d -m 0755 "${INSTALL_DIR}/blueprints"
install -m 0644 "${source_dir}"/home-assistant/blueprints/*.yaml \
  "${INSTALL_DIR}/blueprints/"
printf '%s\n' "${latest_version}" > "${INSTALL_DIR}/.version"
systemctl daemon-reload
monitor_started_at="$(date --iso-8601=seconds)"
systemctl restart vps-monitor
systemctl is-active --quiet vps-monitor
if ! wait_for_monitor_mqtt "${monitor_started_at}"; then
  journalctl -u vps-monitor -n 30 --no-pager || true
  false
fi
upgrade_started=false
trap - ERR

mapfile -t old_backups < <(
  find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
    -printf '%T@ %p\n' | sort -rn | tail -n +2 | cut -d' ' -f2-
)
cleanup_ok=true
for old_backup in "${old_backups[@]}"; do
  case "${old_backup}" in
    "${BACKUP_ROOT}/"*)
      if ! rm -rf -- "${old_backup}"; then
        cleanup_ok=false
        yellow "無法清理舊版備份：${old_backup}"
      fi
      ;;
  esac
done
green "VPS Sentinel 已安全升級至 ${latest_version}"
green "監控服務、MQTT 認證與在線資料均已驗證"
if [[ -f "${CARD_TARGET}" ]]; then
  green "Apple 卡片前端檔案已同步，不需要重新啟動 Home Assistant"
  yellow "請將 Home Assistant 儀表板資源更新為："
  echo "  /local/vps-sentinel-apple-card.js?v=${latest_version}"
fi
if [[ "${cleanup_ok}" == "true" ]]; then
  green "舊版暫存已清理，僅保留最近一份回復備份"
else
  yellow "升級已完成，但部分舊版備份需要稍後手動清理"
fi
