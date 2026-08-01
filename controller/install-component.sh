#!/usr/bin/env bash
set -Eeuo pipefail

readonly INSTALL_DIR="/opt/vps-sentinel-controller"
readonly DATA_DIR="/var/lib/vps-sentinel-controller"
readonly ENV_FILE="/etc/vps-sentinel-controller.env"
readonly SERVICE_FILE="/etc/systemd/system/vps-sentinel-controller.service"
readonly SERVICE_USER="vps-sentinel-controller"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly SHARED_DIR="$(cd -- "${SCRIPT_DIR}/../vps-monitor" && pwd)"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

if [[ ${EUID} -ne 0 ]]; then
  red "Controller 元件安裝器需要 root 權限。"
  exit 1
fi

for required in controller.py enrollment.py node_registry.py requirements.txt \
  vps-sentinel-controller.service; do
  [[ -f "${SCRIPT_DIR}/${required}" ]] || {
    red "Controller 來源缺少 ${required}。"
    exit 1
  }
done
[[ -f "${SHARED_DIR}/node_contract.py" ]] || {
  red "共用契約 node_contract.py 不存在。"
  exit 1
}

write_env_line() {
  local key="$1" value="$2"
  if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
    red "${key} 不可包含換行。"
    return 1
  fi
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s="%s"\n' "${key}" "${value}"
}

if [[ ! -f "${ENV_FILE}" ]]; then
  : "${CONTROLLER_MQTT_HOST:?需要 CONTROLLER_MQTT_HOST}"
  : "${CONTROLLER_MQTT_USERNAME:?需要 CONTROLLER_MQTT_USERNAME}"
  : "${CONTROLLER_MQTT_PASSWORD:?需要 CONTROLLER_MQTT_PASSWORD}"
  umask 077
  {
    write_env_line MQTT_HOST "${CONTROLLER_MQTT_HOST}"
    write_env_line MQTT_PORT "${CONTROLLER_MQTT_PORT:-1883}"
    write_env_line MQTT_USERNAME "${CONTROLLER_MQTT_USERNAME}"
    write_env_line MQTT_PASSWORD "${CONTROLLER_MQTT_PASSWORD}"
    write_env_line MQTT_TLS "${CONTROLLER_MQTT_TLS:-false}"
    write_env_line MQTT_CA_FILE "${CONTROLLER_MQTT_CA_FILE:-}"
    write_env_line DISCOVERY_PREFIX "${CONTROLLER_DISCOVERY_PREFIX:-homeassistant}"
    write_env_line CONTROLLER_REFRESH_INTERVAL \
      "${CONTROLLER_REFRESH_INTERVAL:-15}"
    write_env_line CONTROLLER_ENROLLMENT_STORE \
      "${DATA_DIR}/enrollments.json"
  } > "${ENV_FILE}"
  chmod 0600 "${ENV_FILE}"
else
  green "沿用既有 Controller 環境檔，不覆寫 MQTT 憑證。"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip ca-certificates

if ! getent group "${SERVICE_USER}" >/dev/null; then
  groupadd --system "${SERVICE_USER}"
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${SERVICE_USER}" --home-dir "${DATA_DIR}" \
    --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -m 0755 -o root -g root "${INSTALL_DIR}"
install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DATA_DIR}"
install -m 0755 "${SCRIPT_DIR}/controller.py" "${INSTALL_DIR}/controller.py"
install -m 0644 "${SCRIPT_DIR}/enrollment.py" "${INSTALL_DIR}/enrollment.py"
install -m 0644 "${SCRIPT_DIR}/node_registry.py" "${INSTALL_DIR}/node_registry.py"
install -m 0644 "${SHARED_DIR}/node_contract.py" "${INSTALL_DIR}/node_contract.py"
install -m 0644 "${SCRIPT_DIR}/requirements.txt" \
  "${INSTALL_DIR}/requirements.txt"

requirements_hash="$(sha256sum "${INSTALL_DIR}/requirements.txt" | awk '{print $1}')"
installed_hash="$(cat "${INSTALL_DIR}/.requirements.sha256" 2>/dev/null || true)"
if [[ ! -x "${INSTALL_DIR}/venv/bin/python" ||
      "${requirements_hash}" != "${installed_hash}" ]]; then
  systemctl stop vps-sentinel-controller 2>/dev/null || true
  python3 -m venv --clear "${INSTALL_DIR}/venv"
  "${INSTALL_DIR}/venv/bin/pip" install --disable-pip-version-check \
    -r "${INSTALL_DIR}/requirements.txt"
  printf '%s\n' "${requirements_hash}" > \
    "${INSTALL_DIR}/.requirements.sha256"
fi

"${INSTALL_DIR}/venv/bin/python" -m py_compile \
  "${INSTALL_DIR}/controller.py" \
  "${INSTALL_DIR}/enrollment.py" \
  "${INSTALL_DIR}/node_registry.py" \
  "${INSTALL_DIR}/node_contract.py"

install -m 0644 "${SCRIPT_DIR}/vps-sentinel-controller.service" \
  "${SERVICE_FILE}"
systemctl daemon-reload
systemctl enable vps-sentinel-controller
if [[ "${CONTROLLER_START:-true}" == "true" ]]; then
  systemctl restart vps-sentinel-controller
  systemctl is-active --quiet vps-sentinel-controller
fi

green "Controller 元件已安裝。"
