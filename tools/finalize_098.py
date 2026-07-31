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


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start_index] + replacement + text[end_index:]


# Release version and Apple card source.
write("VERSION", "0.9.8\n")

card = read("home-assistant/www/vps-sentinel-apple-card.js")
card = replace_once(
    card,
    'const CARD_VERSION = "0.9.6";',
    'const CARD_VERSION = "0.9.8";',
    "Apple card version",
)
card = replace_once(
    card,
    "          touch-action: manipulation;\n        }\n        }\n        .insight-label {",
    "          touch-action: manipulation;\n        }\n        .insight-label {",
    "Apple card stray CSS brace",
)
write("home-assistant/www/vps-sentinel-apple-card.js", card)

# Changelog entries missing from the previous release and the 0.9.8 stability release.
changelog = read("CHANGELOG.md")
anchor = "---\n\n## 0.9.6"
entries = """---

## 0.9.8 — 1.0 前的穩定性收尾

這個版本不擴張功能，而是把安裝、升級、備份、還原與診斷流程補到可以放心交給日常使用的程度。

### 修正

- 維護操作的完成、失敗、冷卻與拒絕通知改為一次性事件，重新整理後不再重播舊訊息。
- Apple 卡片版本、安裝版本與資源快取參數使用同一個版本來源，並修正一處多餘的 CSS 大括號。
- 單純同步 Apple 前端檔案時不再重啟 Home Assistant，避免正在進行的設定流程失效。
- 安裝器、升級器與 Doctor 會實際驗證 VPS Monitor 的 MQTT 帳密、連線紀錄及在線資料，不再只看 systemd 服務狀態。
- 重新執行安裝器時會優先沿用並同步既有 VPS Monitor MQTT 密碼，避免 Mosquitto 與環境檔不一致。
- 備份與還原正式支援 `compose.yaml`，並相容舊版 `docker-compose.yml`。
- 設定備份加入 Mosquitto 設定與密碼檔；還原後會驗證 Home Assistant、MQTT 與監控資料。
- Tailscale Serve 使用的反向代理設定預設包含 `use_x_forwarded_for` 與本機 trusted proxies，降低 400 Bad Request 的機率。

### 可靠性

- 升級後會驗證前端卡片版本及 MQTT 實際資料；失敗時一併回復程式、服務、版本與前端檔案。
- Doctor 新增 MQTT 密碼同步、Apple 卡片同步、Tailscale Serve／代理檢查與 Home Assistant IP 封鎖清除。
- GitHub Release 發布前會重新執行 ShellCheck、JavaScript、YAML、Python 測試與版本一致性檢查。

## 0.9.7 — 整理專案結構與正式發布流程

這個版本完成維護腳本目錄整理，並補齊從舊版升級到新結構時需要的相容性。

### 改善

- 維護腳本統一放入 `scripts/`，移除根目錄的重複相容連結。
- 修正升級器對搬移後腳本路徑的檢查、安裝與回復流程。
- 統一 `vps-sentinel` 指令的參數轉交與文件範例。
- 建立由 `VERSION` 觸發的 GitHub Release 發布流程。

## 0.9.6"""
changelog = replace_once(changelog, anchor, entries, "CHANGELOG insertion")
write("CHANGELOG.md", changelog)

# Setup installer: preserve credentials, repair local monitor identity, configure proxy defaults,
# and verify real MQTT data before declaring success.
setup = read("setup.sh")
helper_anchor = "\n\nclear\nprintf '\\033[1;35m'"
helper_block = r'''

read_env_file() {
  local key="$1" value
  value="$(sed -n "s/^${key}=//p" "${MONITOR_ENV}" 2>/dev/null | tail -n 1)"
  value="${value#\"}"
  value="${value%\"}"
  printf '%s' "${value}"
}

credential_value() {
  local label="$1"
  sed -n "s/^${label}：//p" "${CREDENTIALS_FILE}" 2>/dev/null | tail -n 1
}

write_credentials() {
  local ha_password="$1" monitor_password="$2" temporary
  ha_password="${ha_password:-$(credential_value "Home Assistant MQTT 密碼")}"
  monitor_password="${monitor_password:-$(credential_value "VPS Monitor MQTT 密碼")}"
  if [[ -z "${ha_password}" && -z "${monitor_password}" ]]; then
    return
  fi
  temporary="$(mktemp)"
  umask 077
  {
    echo "VPS Monitor 安裝憑證"
    echo "更新時間：$(date --iso-8601=seconds)"
    echo
    if [[ -n "${ha_password}" ]]; then
      echo "Home Assistant MQTT 使用者：home-assistant"
      echo "Home Assistant MQTT 密碼：${ha_password}"
    fi
    if [[ -n "${monitor_password}" ]]; then
      echo "VPS Monitor MQTT 使用者：vps-monitor"
      echo "VPS Monitor MQTT 密碼：${monitor_password}"
    fi
  } > "${temporary}"
  install -m 0600 "${temporary}" "${CREDENTIALS_FILE}"
  rm -f -- "${temporary}"
}

mqtt_probe() {
  local host port username password vps_id output
  host="$(read_env_file MQTT_HOST)"
  port="$(read_env_file MQTT_PORT)"
  username="$(read_env_file MQTT_USERNAME)"
  password="$(read_env_file MQTT_PASSWORD)"
  vps_id="$(read_env_file VPS_ID)"
  [[ -n "${host}" && -n "${username}" && -n "${vps_id}" ]] || return 1
  output="$(timeout 8 mosquitto_sub \
    -h "${host}" -p "${port:-1883}" \
    -u "${username}" -P "${password}" \
    -t "vps/${vps_id}/online" -C 1 2>&1)" || return 1
  grep -qx 'ON' <<< "${output}"
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

ensure_proxy_settings() {
  python3 - "${HA_DIR}/config/configuration.yaml" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
try:
    start = next(i for i, line in enumerate(lines) if line == "http:")
except StopIteration:
    raise SystemExit(0)

end = len(lines)
for index in range(start + 1, len(lines)):
    line = lines[index]
    if line and not line[0].isspace() and line.rstrip().endswith(":"):
        end = index
        break


def find_key(name):
    prefix = f"  {name}:"
    for index in range(start + 1, end):
        if lines[index].startswith(prefix):
            return index
    return None


server_index = find_key("server_host")
use_index = find_key("use_x_forwarded_for")
if use_index is None:
    use_index = server_index if server_index is not None else start + 1
    lines.insert(use_index, "  use_x_forwarded_for: true")
    end += 1
else:
    lines[use_index] = "  use_x_forwarded_for: true"

trusted_index = find_key("trusted_proxies")
required = ["127.0.0.1", "::1"]
if trusted_index is None:
    lines[use_index + 1:use_index + 1] = [
        "  trusted_proxies:",
        "    - 127.0.0.1",
        '    - "::1"',
    ]
else:
    suffix = lines[trusted_index].split(":", 1)[1].strip()
    if suffix:
        lines[trusted_index:trusted_index + 1] = [
            "  trusted_proxies:",
            "    - 127.0.0.1",
            '    - "::1"',
        ]
    else:
        list_end = trusted_index + 1
        existing = set()
        while list_end < len(lines):
            candidate = lines[list_end]
            if candidate and not candidate.startswith("    "):
                break
            stripped = candidate.strip()
            if stripped.startswith("-"):
                existing.add(stripped[1:].strip().strip('"').strip("'"))
            list_end += 1
        additions = []
        for value in required:
            if value not in existing:
                additions.append(
                    "    - 127.0.0.1" if value == "127.0.0.1" else '    - "::1"'
                )
        lines[list_end:list_end] = additions

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}
'''
setup = replace_once(setup, helper_anchor, helper_block + helper_anchor, "setup helpers")

step3_start = 'generated_ha_password=""\ngenerated_monitor_password=""\n'
step4_marker = 'blue "步驟 4/6：部署 Home Assistant"'
step3_replacement = r'''generated_ha_password=""
generated_monitor_password=""
saved_ha_password="$(credential_value "Home Assistant MQTT 密碼")"
saved_monitor_password="$(credential_value "VPS Monitor MQTT 密碼")"
existing_monitor_host="$(read_env_file MQTT_HOST)"
existing_monitor_username="$(read_env_file MQTT_USERNAME)"
existing_monitor_password="$(read_env_file MQTT_PASSWORD)"
ha_password="${saved_ha_password}"
monitor_password="${existing_monitor_password:-${saved_monitor_password}}"
install -d -m 0755 /etc/mosquitto/conf.d

if [[ ! -e "${MQTT_PASSWD}" ]]; then
  if [[ -z "${ha_password}" ]]; then
    ha_password="$(openssl rand -hex 18)"
    generated_ha_password="${ha_password}"
  fi
  if [[ -z "${monitor_password}" ]]; then
    monitor_password="$(openssl rand -hex 18)"
    generated_monitor_password="${monitor_password}"
  fi
  mosquitto_passwd -b -c "${MQTT_PASSWD}" home-assistant \
    "${ha_password}"
  mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
    "${monitor_password}"
  green "已自動建立兩個 MQTT 專用帳號"
else
  if ! grep -q '^home-assistant:' "${MQTT_PASSWD}"; then
    if [[ -z "${ha_password}" ]]; then
      ha_password="$(openssl rand -hex 18)"
      generated_ha_password="${ha_password}"
    fi
    mosquitto_passwd -b "${MQTT_PASSWD}" home-assistant \
      "${ha_password}"
    green "已新增 home-assistant MQTT 帳號"
  fi
  if ! grep -q '^vps-monitor:' "${MQTT_PASSWD}"; then
    if [[ -z "${monitor_password}" ]]; then
      monitor_password="$(openssl rand -hex 18)"
      generated_monitor_password="${monitor_password}"
    fi
    mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
      "${monitor_password}"
    green "已新增 vps-monitor MQTT 帳號"
  elif [[ -n "${monitor_password}" ]] &&
       { [[ ! -e "${MONITOR_ENV}" ]] ||
         { [[ "${existing_monitor_host}" == "127.0.0.1" ]] &&
           [[ "${existing_monitor_username}" == "vps-monitor" ]]; }; }; then
    mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
      "${monitor_password}"
    green "已同步 VPS Monitor MQTT 密碼"
  fi
fi

chown root:mosquitto "${MQTT_PASSWD}"
chmod 0640 "${MQTT_PASSWD}"
backup_if_exists "${MQTT_CONF}"
cat > "${MQTT_CONF}" <<'MQTT'
per_listener_settings false
allow_anonymous false
password_file /etc/mosquitto/passwd

# Home Assistant 與監控器都在本機，不對公網開放 MQTT。
listener 1883 127.0.0.1
MQTT

systemctl enable mosquitto
if ! systemctl restart mosquitto; then
  red "Mosquitto 無法套用設定，最近的日誌如下："
  journalctl -u mosquitto -n 50 --no-pager || true
  exit 1
fi
if ! systemctl is-active --quiet mosquitto; then
  red "Mosquitto 重啟後未保持運作，最近的日誌如下："
  journalctl -u mosquitto -n 50 --no-pager || true
  exit 1
fi
green "Mosquitto 已啟動，只監聽 127.0.0.1:1883"

write_credentials "${ha_password}" "${monitor_password}"
if [[ -f "${CREDENTIALS_FILE}" ]]; then
  green "MQTT 憑證已保存於 ${CREDENTIALS_FILE}（僅 root 可讀）"
fi

'''
setup = replace_between(setup, step3_start, step4_marker, step3_replacement, "setup MQTT section")

http_old = "http:\n  server_host:"
http_new = "http:\n  use_x_forwarded_for: true\n  trusted_proxies:\n    - 127.0.0.1\n    - \"::1\"\n  server_host:"
if setup.count(http_old) != 2:
    raise RuntimeError(f"setup generated http blocks: expected 2, found {setup.count(http_old)}")
setup = setup.replace(http_old, http_new)

proxy_old = r'''    backup_if_exists "${HA_DIR}/config/configuration.yaml"
    if ! grep -q '^[[:space:]]*use_x_forwarded_for:' \
        "${HA_DIR}/config/configuration.yaml"; then
      sed -i '/^[[:space:]]*server_host:[[:space:]]*$/i\
  use_x_forwarded_for: true\
  trusted_proxies:\
    - 127.0.0.1' "${HA_DIR}/config/configuration.yaml"
    fi
    escaped_ip="${tailscale_ip//./\\.}"
    sed -Ei \
      "/^[[:space:]]*-[[:space:]]*${escaped_ip}[[:space:]]*$/d" \
      "${HA_DIR}/config/configuration.yaml"
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    )
'''
proxy_new = r'''    proxy_backup="${HA_DIR}/config/configuration.yaml.backup.$(date +%Y%m%d-%H%M%S)"
    cp -a "${HA_DIR}/config/configuration.yaml" "${proxy_backup}"
    ensure_proxy_settings
    escaped_ip="${tailscale_ip//./\\.}"
    sed -Ei \
      "/^[[:space:]]*-[[:space:]]*${escaped_ip}[[:space:]]*$/d" \
      "${HA_DIR}/config/configuration.yaml"
    if ! docker exec homeassistant python -m homeassistant \
        --script check_config --config /config; then
      cp -a "${proxy_backup}" "${HA_DIR}/config/configuration.yaml"
      red "反向代理設定驗證失敗，已回復原設定。"
      exit 1
    fi
    (
      cd "${HA_DIR}"
      docker compose restart homeassistant
    )
'''
setup = replace_once(setup, proxy_old, proxy_new, "setup proxy block")

prompt_old = r'''  if [[ -z "${generated_monitor_password}" ]]; then
    ask_secret generated_monitor_password \
      "請輸入既有 vps-monitor MQTT 密碼（輸入時不顯示）"
  fi
'''
prompt_new = r'''  if [[ -z "${monitor_password}" ]]; then
    ask_secret monitor_password \
      "請設定 vps-monitor MQTT 密碼（輸入時不顯示）"
    mosquitto_passwd -b "${MQTT_PASSWD}" vps-monitor \
      "${monitor_password}"
    chown root:mosquitto "${MQTT_PASSWD}"
    chmod 0640 "${MQTT_PASSWD}"
    systemctl restart mosquitto
    write_credentials "${ha_password}" "${monitor_password}"
  fi
'''
setup = replace_once(setup, prompt_old, prompt_new, "setup monitor password prompt")
setup = replace_once(
    setup,
    '    printf \'MQTT_PASSWORD=%s\\n\' "$(env_quote "${generated_monitor_password}")"',
    '    printf \'MQTT_PASSWORD=%s\\n\' "$(env_quote "${monitor_password}")"',
    "setup monitor env password",
)

restart_old = '''systemctl daemon-reload
systemctl enable vps-monitor
systemctl restart vps-monitor
green "VPS Monitor 已啟動並設為開機自動執行"
'''
restart_new = '''systemctl daemon-reload
systemctl enable vps-monitor
monitor_started_at="$(date --iso-8601=seconds)"
systemctl restart vps-monitor
if ! wait_for_monitor_mqtt "${monitor_started_at}"; then
  red "VPS Monitor 未能通過 MQTT 認證與在線資料驗證。"
  journalctl -u vps-monitor -n 30 --no-pager || true
  exit 1
fi
green "VPS Monitor 已啟動，MQTT 認證與在線資料正常"
'''
setup = replace_once(setup, restart_old, restart_new, "setup monitor verification")

ha_password_old = '''if [[ -n "${generated_ha_password}" ]]; then
  echo "  Password：請執行 sudo cat ${CREDENTIALS_FILE} 查看"
else
  echo "  Password：使用你現有的 home-assistant MQTT 密碼"
fi
'''
ha_password_new = '''if [[ -n "${ha_password}" ]]; then
  echo "  Password：請執行 sudo cat ${CREDENTIALS_FILE} 查看"
else
  echo "  Password：使用你現有的 home-assistant MQTT 密碼"
fi
'''
setup = replace_once(setup, ha_password_old, ha_password_new, "setup final HA password hint")
write("setup.sh", setup)

# Update existing interface tests for the dynamic version source.
command_tests = read("tests/test_command_interface.py")
command_tests = replace_once(
    command_tests,
    '        self.assertEqual(VERSION, "0.9.7")',
    '        self.assertEqual(VERSION, "0.9.8")',
    "command test release version",
)
old_resource_assertion = '''        self.assertIn(
            'RESOURCE_URL="/local/vps-sentinel-apple-card.js?v=0.9.7"',
            APPLE_DASHBOARD,
        )
'''
new_resource_assertion = '''        self.assertIn('VERSION_FILE="/opt/vps-monitor/.version"', APPLE_DASHBOARD)
        self.assertIn("resource_url()", APPLE_DASHBOARD)
        self.assertNotIn('RESOURCE_URL="/local/', APPLE_DASHBOARD)
'''
command_tests = replace_once(
    command_tests,
    old_resource_assertion,
    new_resource_assertion,
    "command test dynamic Apple resource",
)
write("tests/test_command_interface.py", command_tests)

# Extend stability tests so normal PR validation blocks inconsistent releases.
release_tests = read("tests/test_release_integrity.py")
release_tests = replace_once(
    release_tests,
    'ROOT = Path(__file__).parents[1]\nAPPLE =',
    'ROOT = Path(__file__).parents[1]\nVERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()\nCARD = (ROOT / "home-assistant/www/vps-sentinel-apple-card.js").read_text(encoding="utf-8")\nCHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")\nSETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")\nAPPLE =',
    "release test fixtures",
)
insert_before = '''    def test_apple_resource_url_uses_installed_version(self):
'''
new_tests = '''    def test_release_version_surfaces_are_consistent(self):
        self.assertEqual(VERSION, "0.9.8")
        self.assertIn(f'const CARD_VERSION = "{VERSION}";', CARD)
        self.assertIn(f"## {VERSION}", CHANGELOG)

    def test_setup_verifies_mqtt_and_preserves_credentials(self):
        self.assertIn("wait_for_monitor_mqtt", SETUP)
        self.assertIn("MQTT 認證與在線資料正常", SETUP)
        self.assertIn("write_credentials", SETUP)
        self.assertIn("已同步 VPS Monitor MQTT 密碼", SETUP)
        self.assertIn("use_x_forwarded_for: true", SETUP)
        self.assertIn('    - "::1"', SETUP)

'''
release_tests = replace_once(
    release_tests,
    insert_before,
    new_tests + insert_before,
    "release test additions",
)
write("tests/test_release_integrity.py", release_tests)
