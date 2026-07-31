from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Install the release version before the monitor starts so MQTT Discovery reports
# the correct software version on the first successful connection.
setup = read("setup.sh")
setup = replace_once(
    setup,
    '''install -m 0644 "${REPO_DIR}/vps-monitor/vps-monitor.service" \\
  /etc/systemd/system/vps-monitor.service
systemctl daemon-reload
''',
    '''install -m 0644 "${REPO_DIR}/vps-monitor/vps-monitor.service" \\
  /etc/systemd/system/vps-monitor.service
install -m 0644 "${REPO_DIR}/VERSION" "${MONITOR_DIR}/.version"
systemctl daemon-reload
''',
    "setup version before monitor start",
)
setup = replace_once(
    setup,
    '''install -m 0644 "${REPO_DIR}/VERSION" "${MONITOR_DIR}/.version"

blue "步驟 6/6：最後檢查"
''',
    '''blue "步驟 6/6：最後檢查"
''',
    "remove late setup version install",
)
write("setup.sh", setup)

# Use the actual card source as the fallback cache version instead of another
# hard-coded release number.
apple = read("scripts/apple-dashboard.sh")
apple = replace_once(
    apple,
    '''installed_version() {
  local version
  version="$(tr -d '[:space:]' < "${VERSION_FILE}" 2>/dev/null || true)"
  if [[ ! "${version}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
    version="0.9.8"
  fi
  printf '%s' "${version}"
}
''',
    '''installed_version() {
  local version
  version="$(tr -d '[:space:]' < "${VERSION_FILE}" 2>/dev/null || true)"
  if [[ ! "${version}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
    version="$(sed -n 's/^const CARD_VERSION = "\\([^"]*\\)";.*/\\1/p' \\
      "${CARD_SOURCE}" | head -n 1)"
  fi
  if [[ ! "${version}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
    version="development"
  fi
  printf '%s' "${version}"
}
''',
    "Apple version fallback",
)
write("scripts/apple-dashboard.sh", apple)

# Restore exact rollback semantics and require a fresh monitor connection after
# an upgrade instead of accepting a possibly stale retained online payload.
upgrade = read("scripts/upgrade.sh")
upgrade = replace_once(
    upgrade,
    '''mqtt_probe() {
  local host port username password vps_id
  host="$(read_env MQTT_HOST)"
  port="$(read_env MQTT_PORT)"
  username="$(read_env MQTT_USERNAME)"
  password="$(read_env MQTT_PASSWORD)"
  vps_id="$(read_env VPS_ID)"
  [[ -n "${host}" && -n "${username}" && -n "${vps_id}" ]] || return 1
  timeout 15 mosquitto_sub \\
    -h "${host}" -p "${port:-1883}" \\
    -u "${username}" -P "${password}" \\
    -t "vps/${vps_id}/online" -C 1 2>/dev/null |
    grep -qx 'ON'
}
''',
    '''mqtt_probe() {
  local host port username password vps_id
  host="$(read_env MQTT_HOST)"
  port="$(read_env MQTT_PORT)"
  username="$(read_env MQTT_USERNAME)"
  password="$(read_env MQTT_PASSWORD)"
  vps_id="$(read_env VPS_ID)"
  [[ -n "${host}" && -n "${username}" && -n "${vps_id}" ]] || return 1
  timeout 15 mosquitto_sub \\
    -h "${host}" -p "${port:-1883}" \\
    -u "${username}" -P "${password}" \\
    -t "vps/${vps_id}/online" -C 1 2>/dev/null |
    grep -qx 'ON'
}

wait_for_monitor_mqtt() {
  local started_at="$1" _
  for _ in {1..15}; do
    if journalctl -u vps-monitor --since "${started_at}" --no-pager \\
        2>/dev/null | grep -q 'MQTT 已連線' && mqtt_probe; then
      return 0
    fi
    sleep 2
  done
  return 1
}
''',
    "upgrade fresh MQTT helper",
)
upgrade = replace_once(
    upgrade,
    '''  if [[ -f "${backup}/vps-sentinel-apple-card.js" ]]; then
    install -m 0644 "${backup}/vps-sentinel-apple-card.js" \\
      "${INSTALL_DIR}/vps-sentinel-apple-card.js"
  fi
  if [[ -f "${backup}/homeassistant-card.js" ]]; then
    install -d -m 0755 "$(dirname "${CARD_TARGET}")"
    install -m 0644 "${backup}/homeassistant-card.js" "${CARD_TARGET}"
  fi
''',
    '''  if [[ -f "${backup}/vps-sentinel-apple-card.js" ]]; then
    install -m 0644 "${backup}/vps-sentinel-apple-card.js" \\
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
''',
    "upgrade card rollback",
)
upgrade = replace_once(
    upgrade,
    '''  for name in vps-sentinel vps-sentinel-update vps-sentinel-uninstall \\
    vps-sentinel-upgrade vps-sentinel-doctor vps-sentinel-backup \\
    vps-sentinel-automations vps-sentinel-apple; do
    [[ ! -f "${backup}/${name}" ]] ||
      install -m 0755 "${backup}/${name}" "/usr/local/sbin/${name}"
  done
''',
    '''  for name in vps-sentinel vps-sentinel-update vps-sentinel-uninstall \\
    vps-sentinel-upgrade vps-sentinel-doctor vps-sentinel-backup \\
    vps-sentinel-automations vps-sentinel-apple; do
    if [[ -f "${backup}/${name}" ]]; then
      install -m 0755 "${backup}/${name}" "/usr/local/sbin/${name}"
    else
      rm -f -- "/usr/local/sbin/${name}"
    fi
  done
''',
    "upgrade command rollback",
)
upgrade = replace_once(
    upgrade,
    '''systemctl daemon-reload
systemctl restart vps-monitor
sleep 5
systemctl is-active --quiet vps-monitor
mqtt_probe
upgrade_started=false
''',
    '''systemctl daemon-reload
monitor_started_at="$(date --iso-8601=seconds)"
systemctl restart vps-monitor
systemctl is-active --quiet vps-monitor
if ! wait_for_monitor_mqtt "${monitor_started_at}"; then
  journalctl -u vps-monitor -n 30 --no-pager || true
  false
fi
upgrade_started=false
''',
    "upgrade fresh MQTT verification",
)
upgrade = replace_once(
    upgrade,
    '''if [[ -f "${CARD_TARGET}" ]]; then
  green "Apple 卡片前端檔案已同步，不需要重新啟動 Home Assistant"
fi
''',
    '''if [[ -f "${CARD_TARGET}" ]]; then
  green "Apple 卡片前端檔案已同步，不需要重新啟動 Home Assistant"
  yellow "請將 Home Assistant 儀表板資源更新為："
  echo "  /local/vps-sentinel-apple-card.js?v=${latest_version}"
fi
''',
    "upgrade cache-busting guidance",
)
write("scripts/upgrade.sh", upgrade)

# Keep the root-only credential record synchronized when Doctor repairs the
# monitor account.
doctor = read("scripts/doctor.sh")
doctor = replace_once(
    doctor,
    'readonly MQTT_PASSWD="/etc/mosquitto/passwd"\n',
    'readonly MQTT_PASSWD="/etc/mosquitto/passwd"\nreadonly CREDENTIALS_FILE="/root/vps-homeassistant-credentials.txt"\n',
    "doctor credentials constant",
)
doctor = replace_once(
    doctor,
    '''reset_monitor_mqtt_password() {
''',
    '''save_monitor_credential() {
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
path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
PY
  chmod 0600 "${CREDENTIALS_FILE}"
}

reset_monitor_mqtt_password() {
''',
    "doctor save credential helper",
)
doctor = replace_once(
    doctor,
    '''    rm -f -- "${backup_passwd}" "${backup_env}"
    green "VPS Monitor MQTT 密碼已同步，實際登入成功"
    return
''',
    '''    save_monitor_credential "${new_password}"
    rm -f -- "${backup_passwd}" "${backup_env}"
    green "VPS Monitor MQTT 密碼已同步，實際登入成功"
    green "新密碼已保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
    return
''',
    "doctor persist repaired credential",
)
write("scripts/doctor.sh", doctor)

# Make committed whitespace checks meaningful in both PR and release workflows.
validate = read(".github/workflows/validate.yml")
validate = replace_once(
    validate,
    '''      - name: Check whitespace errors
        run: git diff --check
''',
    '''      - name: Check whitespace errors
        shell: bash
        run: |
          if [[ "${{ github.event_name }}" == "pull_request" ]]; then
            git diff --check "${{ github.event.pull_request.base.sha }}...HEAD"
          else
            git diff --check HEAD^ HEAD
          fi
''',
    "validate whitespace check",
)
write(".github/workflows/validate.yml", validate)

release = read(".github/workflows/release.yml")
release = replace_once(
    release,
    '''      - name: Check whitespace errors
        run: git diff --check
''',
    '''      - name: Check whitespace errors
        run: git diff --check HEAD^ HEAD
''',
    "release whitespace check",
)
write(".github/workflows/release.yml", release)

# Regression assertions for the final polish pass.
tests = read("tests/test_release_integrity.py")
tests = replace_once(
    tests,
    '''        self.assertIn("use_x_forwarded_for: true", SETUP)
        self.assertIn('    - "::1"', SETUP)
''',
    '''        self.assertIn("use_x_forwarded_for: true", SETUP)
        self.assertIn('    - "::1"', SETUP)
        self.assertLess(
            SETUP.index('install -m 0644 "${REPO_DIR}/VERSION"'),
            SETUP.index('monitor_started_at="$(date --iso-8601=seconds)"'),
        )
''',
    "setup version order test",
)
tests = replace_once(
    tests,
    '''        self.assertIn("不需要重新啟動 Home Assistant", APPLE)
''',
    '''        self.assertIn("不需要重新啟動 Home Assistant", APPLE)
        self.assertIn("CARD_VERSION", APPLE)
        self.assertNotIn('version="0.9.8"', APPLE)
''',
    "Apple fallback test",
)
tests = replace_once(
    tests,
    '''        self.assertIn("Apple 卡片已同步", DOCTOR)
''',
    '''        self.assertIn("Apple 卡片已同步", DOCTOR)
        self.assertIn("save_monitor_credential", DOCTOR)
        self.assertIn("vps-homeassistant-credentials.txt", DOCTOR)
''',
    "Doctor credential test",
)
tests = replace_once(
    tests,
    '''        self.assertIn("MQTT 認證與在線資料均已驗證", UPGRADE)
''',
    '''        self.assertIn("MQTT 認證與在線資料均已驗證", UPGRADE)
        self.assertIn("wait_for_monitor_mqtt", UPGRADE)
        self.assertIn('rm -f -- "${CARD_TARGET}"', UPGRADE)
        self.assertIn("/local/vps-sentinel-apple-card.js?v=${latest_version}", UPGRADE)
''',
    "upgrade rollback test",
)
write("tests/test_release_integrity.py", tests)
