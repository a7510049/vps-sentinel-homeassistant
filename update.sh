#!/usr/bin/env bash
set -Eeuo pipefail

readonly HA_DIR="/opt/homeassistant"
readonly BACKUP_DIR="/opt/homeassistant-backups"
readonly IMAGE="ghcr.io/home-assistant/home-assistant:stable"

green()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m⚠ %s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; }

if [[ ${EUID} -ne 0 ]]; then
  red "請使用 sudo：sudo bash update.sh"
  exit 1
fi

if [[ ! -f "${HA_DIR}/compose.yaml" ||
      ! -d "${HA_DIR}/config" ]]; then
  red "找不到由本專案管理的 Home Assistant Container。"
  exit 1
fi

printf '\033[1;35m'
cat <<'BANNER'
╭────────────────────────────────────────╮
│  🏠 Home Assistant 安全更新            │
╰────────────────────────────────────────╯
BANNER
printf '\033[0m'

current_image_id="$(docker inspect --format '{{.Image}}' homeassistant \
  2>/dev/null || true)"
current_version="$(docker inspect \
  --format '{{index .Config.Labels \"io.hass.version\"}}' homeassistant \
  2>/dev/null || true)"
echo "目前版本：${current_version:-無法判斷}"
echo "更新前會先驗證設定並建立備份，啟動失敗時自動退回。"
echo
read -r -p "是否檢查並更新 Home Assistant [y/N]：" answer
case "${answer,,}" in
  y|yes|是) ;;
  *) echo "已取消更新。"; exit 0 ;;
esac

echo "正在檢查 Home Assistant 設定。"
if ! docker exec homeassistant python -m homeassistant \
    --script check_config --config /config; then
  red "設定檢查未通過，已取消更新。"
  exit 1
fi

docker pull "${IMAGE}"
new_image_id="$(docker image inspect --format '{{.Id}}' "${IMAGE}")"
if [[ -n "${current_image_id}" &&
      "${new_image_id}" == "${current_image_id}" ]]; then
  green "目前已是最新映像，不需要更新。"
  exit 0
fi

install -d -m 0700 "${BACKUP_DIR}"
timestamp="$(date +%Y%m%d-%H%M%S)"
backup="${BACKUP_DIR}/homeassistant-config-${timestamp}.tar.gz"
tar -C "${HA_DIR}" -czf "${backup}" config
chmod 0600 "${backup}"
green "設定已備份：${backup}"

if [[ -n "${current_image_id}" ]]; then
  docker tag "${current_image_id}" \
    "ghcr.io/home-assistant/home-assistant:vps-sentinel-rollback"
fi

(
  cd "${HA_DIR}"
  docker compose up -d homeassistant
)

ready=false
for _ in {1..60}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8123/ \
      >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 3
done

if [[ "${ready}" == "true" ]]; then
  cleanup_ok=true
  new_version="$(docker inspect \
    --format '{{index .Config.Labels \"io.hass.version\"}}' homeassistant \
    2>/dev/null || true)"
  mapfile -t old_backups < <(
    find "${BACKUP_DIR}" -maxdepth 1 -type f \
      -name 'homeassistant-config-*.tar.gz' -printf '%T@ %p\n' |
      sort -rn | tail -n +2 | cut -d' ' -f2-
  )
  for old_backup in "${old_backups[@]}"; do
    case "${old_backup}" in
      "${BACKUP_DIR}/homeassistant-config-"*.tar.gz)
        if ! rm -f -- "${old_backup}"; then
          cleanup_ok=false
          yellow "無法清理舊備份：${old_backup}"
        fi
        ;;
    esac
  done
  docker image rm \
    "ghcr.io/home-assistant/home-assistant:vps-sentinel-rollback" \
    >/dev/null 2>&1 || true
  green "Home Assistant 更新完成：${new_version:-版本未知}"
  if [[ "${cleanup_ok}" == "true" ]]; then
    green "更新暫存已清理，僅保留最近一份設定備份"
  else
    yellow "更新已完成，但部分舊備份需要稍後手動清理"
  fi
  exit 0
fi

red "更新後 3 分鐘內未恢復，正在退回原本映像。"
if [[ -n "${current_image_id}" ]]; then
  docker tag \
    "ghcr.io/home-assistant/home-assistant:vps-sentinel-rollback" \
    "${IMAGE}"
  (
    cd "${HA_DIR}"
    docker compose up -d --force-recreate homeassistant
  )
  yellow "已退回原本映像。設定備份保留於：${backup}"
else
  red "找不到原本映像，無法自動退回。設定備份位於：${backup}"
fi
exit 1
