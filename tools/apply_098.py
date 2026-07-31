from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    write(path, content.replace(old, new, 1))


write("VERSION", "0.9.8")

replace_once(
    "home-assistant/www/vps-sentinel-apple-card.js",
    'const CARD_VERSION = "0.9.6";',
    'const CARD_VERSION = "0.9.8";',
)
replace_once(
    "home-assistant/www/vps-sentinel-apple-card.js",
    "        }\n        }\n        .insight-label {",
    "        }\n        .insight-label {",
)

old_credentials = '''if [[ -n "${generated_ha_password}" || -n "${generated_monitor_password}" ]]; then
  umask 077
  {
    echo "VPS Monitor 安裝憑證"
    echo "建立時間：$(date --iso-8601=seconds)"
    echo
    [[ -n "${generated_ha_password}" ]] && \\
      echo "Home Assistant MQTT 使用者：home-assistant"
    [[ -n "${generated_ha_password}" ]] && \\
      echo "Home Assistant MQTT 密碼：${generated_ha_password}"
    [[ -n "${generated_monitor_password}" ]] && \\
      echo "VPS Monitor MQTT 使用者：vps-monitor"
    [[ -n "${generated_monitor_password}" ]] && \\
      echo "VPS Monitor MQTT 密碼：${generated_monitor_password}"
  } > "${CREDENTIALS_FILE}"
  chmod 0600 "${CREDENTIALS_FILE}"
  green "新密碼已保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
fi'''
new_credentials = '''if [[ -n "${generated_ha_password}" || -n "${generated_monitor_password}" ]]; then
  umask 077
  credentials_tmp="$(mktemp)"
  HA_PASSWORD="${generated_ha_password}" \\
  MONITOR_PASSWORD="${generated_monitor_password}" \\
  python3 - "${CREDENTIALS_FILE}" "${credentials_tmp}" <<'PY'
from pathlib import Path
import os
import sys
source = Path(sys.argv[1])
target = Path(sys.argv[2])
values = {}
if source.exists():
    for line in source.read_text(encoding="utf-8").splitlines():
        if "：" in line:
            key, value = line.split("：", 1)
            values[key] = value
if os.environ.get("HA_PASSWORD"):
    values["Home Assistant MQTT 使用者"] = "home-assistant"
    values["Home Assistant MQTT 密碼"] = os.environ["HA_PASSWORD"]
if os.environ.get("MONITOR_PASSWORD"):
    values["VPS Monitor MQTT 使用者"] = "vps-monitor"
    values["VPS Monitor MQTT 密碼"] = os.environ["MONITOR_PASSWORD"]
lines = ["VPS Monitor 安裝憑證", "建立時間：由 setup.sh 更新", ""]
for key in (
    "Home Assistant MQTT 使用者",
    "Home Assistant MQTT 密碼",
    "VPS Monitor MQTT 使用者",
    "VPS Monitor MQTT 密碼",
):
    if key in values:
        lines.append(f"{key}：{values[key]}")
target.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
PY
  install -m 0600 "${credentials_tmp}" "${CREDENTIALS_FILE}"
  rm -f -- "${credentials_tmp}"
  green "新密碼已合併保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
fi'''
replace_once("setup.sh", old_credentials, new_credentials)

old_http = '''http:
  server_host:
    - 127.0.0.1
    - ${tailscale_ip}
  ip_ban_enabled: true
  login_attempts_threshold: 5'''
new_http = '''http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
    - "::1"
  server_host:
    - 127.0.0.1
    - ${tailscale_ip}
  ip_ban_enabled: true
  login_attempts_threshold: 5'''
setup = read("setup.sh")
if setup.count(old_http) != 2:
    raise RuntimeError("setup.sh: expected two Home Assistant HTTP blocks")
write("setup.sh", setup.replace(old_http, new_http))

replace_once(
    "setup.sh",
    '''systemctl restart vps-monitor
green "VPS Monitor 已啟動並設為開機自動執行"''',
    '''systemctl restart vps-monitor
mqtt_ready=false
for _ in {1..10}; do
  mqtt_host="$(sed -n 's/^MQTT_HOST=//p' "${MONITOR_ENV}" | tail -n 1 | tr -d '\"')"
  mqtt_port="$(sed -n 's/^MQTT_PORT=//p' "${MONITOR_ENV}" | tail -n 1 | tr -d '\"')"
  mqtt_user="$(sed -n 's/^MQTT_USERNAME=//p' "${MONITOR_ENV}" | tail -n 1 | tr -d '\"')"
  mqtt_password="$(sed -n 's/^MQTT_PASSWORD=//p' "${MONITOR_ENV}" | tail -n 1 | tr -d '\"')"
  mqtt_vps_id="$(sed -n 's/^VPS_ID=//p' "${MONITOR_ENV}" | tail -n 1 | tr -d '\"')"
  if timeout 8 mosquitto_sub \\
      -h "${mqtt_host}" -p "${mqtt_port:-1883}" \\
      -u "${mqtt_user}" -P "${mqtt_password}" \\
      -t "vps/${mqtt_vps_id}/online" -C 1 2>/dev/null | grep -qx ON; then
    mqtt_ready=true
    break
  fi
  sleep 2
done
if [[ "${mqtt_ready}" != "true" ]]; then
  red "VPS Monitor 已啟動，但 MQTT 認證或資料回報未通過。"
  journalctl -u vps-monitor -n 50 --no-pager || true
  exit 1
fi
green "VPS Monitor 已啟動，MQTT 認證與在線資料正常"''',
)

replace_once(
    "tests/test_command_interface.py",
    'self.assertEqual(VERSION, "0.9.7")',
    'self.assertEqual(VERSION, "0.9.8")',
)
replace_once(
    "tests/test_command_interface.py",
    '''        self.assertIn(
            'RESOURCE_URL="/local/vps-sentinel-apple-card.js?v=0.9.7"',
            APPLE_DASHBOARD,
        )''',
    '''        self.assertIn('VERSION_FILE="/opt/vps-monitor/.version"', APPLE_DASHBOARD)
        self.assertIn("resource_url()", APPLE_DASHBOARD)
        self.assertNotIn("?v=0.9.7", APPLE_DASHBOARD)''',
)

validate = read(".github/workflows/validate.yml")
needle = "          tests/test_command_interface.py\n"
if "tests/test_release_integrity.py" not in validate:
    if needle not in validate:
        raise RuntimeError("validate workflow Python syntax block not found")
    validate = validate.replace(
        needle,
        needle + "          tests/test_release_integrity.py\n",
        1,
    )
write(".github/workflows/validate.yml", validate)

changelog = read("CHANGELOG.md")
marker = "---\n\n"
entry = '''## 0.9.8 — 1.0 前的可靠性收尾

這個版本不擴張功能，而是把安裝、升級、備份與診斷的最後幾個不確定因素收乾淨，作為 1.0 前的穩定基線。

### 修正

- 正式收錄維護通知不再於重新整理後重播的修正，並以 request ID 對應每次操作。
- 修正 Apple 卡片內部版本仍停留在 0.9.6，以及樣式表多餘大括號造成的解析風險。
- Apple 前端檔案更新不再重新啟動 Home Assistant，避免正在進行的整合設定流程失效。
- 備份與還原改用實際的 `compose.yaml`，並相容舊版 `docker-compose.yml`。
- 備份新增 Mosquitto 設定與密碼檔，避免還原後監控環境與 MQTT 帳密不同步。
- 安裝器保留既有憑證內容，只更新本次新建立的帳號。

### 可靠性

- 安裝、升級與還原會實際驗證 MQTT 認證與在線資料，不再只檢查 systemd 顯示 `active`。
- Doctor 新增 MQTT 密碼同步、Apple 卡片同步、Tailscale Serve／反向代理檢查，以及有確認保護的 IP 封鎖清除。
- 發布工作會在建立 Release 前重新執行語法、測試與版本一致性檢查。

### 升級提醒

- 從 0.9.7 升級後請執行一次 `sudo vps-sentinel apple`，同步 Home Assistant 前端檔案並依畫面更新資源網址版本參數。之後的版本升級會自動同步已安裝的前端檔案。

## 0.9.7 — 讓安裝、更新與專案結構重新對齊

### 修正

- 維護腳本統一移至 `scripts/`，並修正安裝器與升級器的來源路徑。
- 統一 `vps-sentinel` 指令參數轉送，讓 `apple --apply` 等子命令可正常執行。
- 補強下載內容、語法與檔案完整性驗證。

'''
if "## 0.9.8" not in changelog:
    if marker not in changelog:
        raise RuntimeError("CHANGELOG marker not found")
    changelog = changelog.replace(marker, marker + entry, 1)
write("CHANGELOG.md", changelog)

print("Applied 0.9.8 release patches")
