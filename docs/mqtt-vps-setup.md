# Ubuntu VPS 部署 MQTT 與 Home Assistant

這份指南適用於以下架構：

> 一般使用者建議從專案根目錄執行 `sudo bash setup.sh`。第 7 節的 `vps-monitor/install.sh` 是只安裝監控服務的進階／獨立部署方式，不會安裝完整維護指令集或 Home Assistant。

```text
iPhone Home Assistant App
           │
     Tailscale 私網
           │
Ubuntu VPS
├── Home Assistant Container
├── Mosquitto MQTT Broker
└── VPS Monitor
```

Home Assistant、Mosquitto 與 VPS Monitor 位於同一台 VPS，因此 MQTT
只需監聽 `127.0.0.1:1883`，不必公開到網際網路或 Tailscale。

## 1. 安裝 Mosquitto

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

## 2. 建立專用帳號

建立 VPS Monitor 帳號：

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd vps-monitor
```

建立 Home Assistant 帳號：

```bash
sudo mosquitto_passwd /etc/mosquitto/passwd home-assistant
```

兩個帳號應使用不同的高強度密碼。修正密碼檔權限：

```bash
sudo chown root:mosquitto /etc/mosquitto/passwd
sudo chmod 640 /etc/mosquitto/passwd
```

確認結果：

```bash
sudo ls -l /etc/mosquitto/passwd
```

應類似：

```text
-rw-r----- 1 root mosquitto ... /etc/mosquitto/passwd
```

## 3. 設定 Mosquitto

```bash
sudo nano /etc/mosquitto/conf.d/home-assistant.conf
```

填入：

```conf
per_listener_settings false
allow_anonymous false
password_file /etc/mosquitto/passwd

listener 1883 127.0.0.1
```

不要在這個檔案重複加入以下設定：

```conf
persistence true
persistence_location /var/lib/mosquitto/
log_dest syslog
```

Ubuntu 的 `/etc/mosquitto/mosquitto.conf` 通常已包含持久化與日誌設定。
重複設定 `persistence_location` 會導致：

```text
Error: Duplicate persistence_location value in configuration
```

重新啟動並檢查：

```bash
sudo systemctl restart mosquitto
sudo systemctl status mosquitto --no-pager
sudo ss -lntp | grep 1883
```

> Ubuntu 內建的 Mosquitto 2.0.18 不支援 `mosquitto -t`。服務若無法
> 重啟，使用 `sudo journalctl -u mosquitto -n 50 --no-pager` 查看
> 實際設定錯誤。

正確結果只應監聽：

```text
127.0.0.1:1883
```

## 4. 測試 MQTT 帳密

以下方式不會把真實密碼直接寫入 shell history：

```bash
read -rsp "MQTT 密碼：" MQTT_PASS
echo
mosquitto_sub -h 127.0.0.1 -p 1883 \
  -u vps-monitor -P "$MQTT_PASS" \
  -t test/hello -C 1 &
sleep 1
mosquitto_pub -h 127.0.0.1 -p 1883 \
  -u vps-monitor -P "$MQTT_PASS" \
  -t test/hello -m "MQTT 測試成功"
wait
unset MQTT_PASS
```

正常會輸出：

```text
MQTT 測試成功
```

## 5. 部署 Home Assistant Container

確認 Docker 已安裝：

```bash
docker --version
docker compose version
```

建立目錄：

```bash
sudo mkdir -p /opt/homeassistant/config
cd /opt/homeassistant
sudo nano compose.yaml
```

填入：

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    restart: unless-stopped
    network_mode: host
    environment:
      TZ: Asia/Taipei
    volumes:
      - /opt/homeassistant/config:/config
```

啟動：

```bash
sudo docker compose config
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

如果 Home Assistant 只透過 Tailscale 存取，可在
`/opt/homeassistant/config/configuration.yaml` 加入：

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
  server_host:
    - 127.0.0.1
  ip_ban_enabled: true
  login_attempts_threshold: 5
```

檢查後重啟，接著啟用 tailnet 私有的 Tailscale Serve：

```bash
sudo docker exec homeassistant python -m homeassistant \
  --script check_config --config /config
sudo docker restart homeassistant
sudo tailscale serve --bg http://127.0.0.1:8123
sudo tailscale serve status
```

Tailscale Serve 會顯示一個僅限 tailnet 存取的 `https://*.ts.net` 網址，
並自動管理 TLS 憑證。第一次使用時，可能需要在瀏覽器確認啟用 HTTPS。
不要使用 Funnel，否則服務會公開到網際網路。

## 6. 在 Home Assistant 加入 MQTT

於 Home Assistant App 進入：

```text
設定 → 裝置與服務 → 新增整合 → MQTT
```

填寫：

```text
Broker：127.0.0.1
Port：1883
Username：home-assistant
Password：步驟 2 設定的密碼
TLS：關閉
MQTT Discovery：開啟
Discovery Prefix：homeassistant
```

Home Assistant Container 使用 host network，因此可直接連線
`127.0.0.1:1883`。

### 從 Home Assistant 測試

進入 MQTT 整合的「設定」：

1. 監聽主題填入 `test/#` 並開始監聽。
2. 發布主題填入 `test/hello`。
3. Payload 填入 `Home Assistant MQTT 成功`。
4. 按「發布」。

監聽區收到相同訊息即代表設定成功。

## 7. 安裝 VPS Monitor

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git
sudo bash vps-sentinel-homeassistant/vps-monitor/install.sh
```

建議設定：

```text
MQTT Broker：127.0.0.1
TLS：否
Port：1883
Username：vps-monitor
Password：步驟 2 設定的密碼
資源模式：平衡
網路速率：關閉
監控服務：ssh mosquitto docker
```

## 8. 常見問題

### Mosquitto 顯示 `status=13`

通常是密碼檔權限錯誤：

```bash
sudo chown root:mosquitto /etc/mosquitto/passwd
sudo chmod 640 /etc/mosquitto/passwd
sudo systemctl restart mosquitto
```

### 所有 MQTT 實體同時顯示「不可用」

先檢查：

```bash
sudo systemctl status mosquitto vps-monitor --no-pager -l
sudo ss -lntp | grep 1883
sudo journalctl -u mosquitto -n 50 --no-pager
sudo journalctl -u vps-monitor -n 50 --no-pager
```

常見原因是 Mosquitto 綁定 Tailscale IP，但開機時 Tailscale 尚未建立
該 IP。這套同機部署不需要讓 MQTT 監聽 Tailscale，請維持：

```conf
listener 1883 127.0.0.1
```

再重新啟動：

```bash
sudo systemctl restart mosquitto
sudo systemctl restart vps-monitor
```

### Home Assistant 出現 Bluetooth 權限錯誤

VPS 沒有藍牙硬體時可以忽略。不要只為了消除這項訊息就將 Home
Assistant Container 設為 privileged。

## 9. 日常維護

```bash
# MQTT 狀態
systemctl status mosquitto

# VPS Monitor 狀態與日誌
systemctl status vps-monitor
journalctl -u vps-monitor -f

# 更新 VPS Sentinel 本身
sudo vps-sentinel upgrade

# 使用備份與回退機制更新 Home Assistant
sudo vps-sentinel ha-update
```
