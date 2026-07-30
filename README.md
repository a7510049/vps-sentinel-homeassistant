# 🖥️ VPS Sentinel for Home Assistant

> 用 Home Assistant 查看 VPS 狀態，介面簡單、資源占用低，適合免費或小型 VPS。

VPS Sentinel 會自動把 VPS 的狀態送進 Home Assistant，讓你用手機查看：

- CPU、記憶體與磁碟使用率
- 主機是否正常連線
- 系統是否需要安全更新或重新啟動
- Docker 容器與指定服務是否正常
- VPS 所在國家、供應商與作業系統

資料透過 MQTT 傳送，裝置會自動出現在 Home Assistant，不需要逐一建立感測器。

## 先確認是否適合你

建議使用：

- Ubuntu 22.04 LTS 或 24.04 LTS
- 一般 `x86_64` 或 `arm64` VPS
- 可使用 `sudo` 的帳號
- VPS 至少保留約 1 GB 可用記憶體

支援程度：

| 系統 | 支援狀態 |
| --- | --- |
| Ubuntu 22.04／24.04 LTS | ✅ 正式支援 |
| Debian 12／13 | 🧪 可測試使用 |
| 其他 Linux 發行版 | ❌ 目前不支援 |
| Windows／macOS | ❌ 不支援 |

> Home Assistant、Mosquitto 與 VPS Sentinel 可以全部安裝在同一台 VPS，不需要讓家中電腦一直開機。

## 🚀 第一次安裝

在 Ubuntu VPS 貼上這一行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash setup.sh
```

安裝器會用中文詢問你要安裝哪些項目，並協助設定：

1. Mosquitto MQTT
2. Home Assistant Container
3. Tailscale 安全連線
4. VPS Sentinel 監控程式
5. Home Assistant 儀表板

大多數使用者可以直接採用推薦選項。安裝完成後，畫面會顯示：

- Home Assistant 網址
- MQTT 帳號與連線資料
- 下一步該做什麼

### 安裝後還要做兩件事

#### 1. 在 Home Assistant 加入 MQTT

前往：

**設定 → 裝置與服務 → 新增整合 → MQTT**

填入安裝完成時顯示的 MQTT 資料。一般同機安裝會是：

```text
Broker：127.0.0.1
Port：1883
Username：home-assistant
Password：安裝時設定的密碼
TLS：關閉
```

完成後，VPS 的感測器會自動出現在 Home Assistant。

需要逐步圖文說明時，請看：

**[MQTT 與 Home Assistant 完整安裝教學](docs/mqtt-vps-setup.md)**

#### 2. 建立 Apple 風格儀表板

執行：

```bash
sudo vps-sentinel-apple --apply
```

接著重新整理 Home Assistant。儀表板會顯示 CPU、記憶體、磁碟、主機資訊與健康狀態。

若仍看到舊版卡片，請確認資源網址是：

```text
/local/vps-sentinel-apple-card.js?v=0.9.1
```

## 📱 手機如何使用

1. 安裝 Home Assistant Companion App。
2. 手機開啟 Tailscale，並登入與 VPS 相同的 Tailscale 帳號。
3. 在 App 加入安裝器顯示的 Home Assistant 網址。

只要 VPS 持續運作，家中電腦可以關機。

目前預設使用 Tailscale 保護 Home Assistant，因此人在外面時也要開啟 Tailscale。這比直接把 Home Assistant 管理介面公開到網路上安全。

## 🧰 日常使用

平常只要執行：

```bash
sudo vps-sentinel
```

會開啟中文維護中心，可查看狀態、調整設定、更新或移除。

常用指令：

| 想做的事 | 指令 |
| --- | --- |
| 查看目前狀態 | `sudo vps-sentinel status` |
| 修改監控設定 | `sudo vps-sentinel settings` |
| 重新建立儀表板 | `sudo vps-sentinel dashboard` |
| 自動檢查與修復 | `sudo vps-sentinel doctor` |
| 備份設定 | `sudo vps-sentinel backup` |
| 更新 VPS Sentinel | `sudo vps-sentinel upgrade` |
| 更新 Home Assistant | `sudo vps-sentinel ha-update` |
| 查看所有指令 | `sudo vps-sentinel help` |

## 🔄 如何更新

更新 VPS Sentinel：

```bash
sudo vps-sentinel upgrade
```

更新完成後，建議重新套用儀表板：

```bash
sudo vps-sentinel-apple --apply
```

更新 Home Assistant：

```bash
sudo vps-sentinel ha-update
```

更新流程會先備份必要檔案。成功後會清除舊的暫存備份，避免長期留下垃圾。

## 🛡️ 主機維護按鈕

0.9.1 起，儀表板可選擇顯示：

- 檢查可用更新
- 安裝 Ubuntu 安全更新
- 重新啟動 VPS

這些遠端操作預設關閉。若需要使用，執行：

```bash
sudo vps-sentinel settings
```

再開啟「Home Assistant 遠端維護」。

安全設計包含：

- 只能執行預先允許的三種操作
- 不接受自訂 Shell 指令
- 每次操作都要在儀表板確認
- 過期或重複的 MQTT 指令會被拒絕
- 操作之間設有冷卻時間

如果你只想監控，不需要遠端控制，保持關閉即可。

## 🚨 異常時先做什麼

執行一鍵檢查：

```bash
sudo vps-sentinel doctor
```

它會檢查：

- VPS Sentinel
- Mosquitto MQTT
- Home Assistant
- Docker
- Tailscale
- 磁碟空間與設定檔

查看即時監控日誌：

```bash
sudo journalctl -u vps-monitor -f
```

查看 Home Assistant 日誌：

```bash
sudo docker logs homeassistant --tail 100
```

### 所有卡片突然顯示「不可用」

通常代表 MQTT 或監控服務剛重新啟動。先等待約一分鐘，再執行：

```bash
sudo systemctl restart mosquitto vps-monitor
```

若仍未恢復，再執行 `sudo vps-sentinel doctor`。

## 📦 備份與移除

建立設定備份：

```bash
sudo vps-sentinel backup
```

備份會存放在：

```text
/opt/vps-sentinel-backups
```

完整移除：

```bash
sudo vps-sentinel-uninstall
```

移除器會先列出選項，不會直接刪除 Home Assistant、Mosquitto、Docker 或 Tailscale。只有你明確選擇後才會處理相關元件。

## 🍎 HomeKit 是選配，不是必要條件

沒有 HomePod 或 Apple TV，仍可正常使用：

- Home Assistant 儀表板
- Companion App
- 手機通知
- Tailscale 遠端連線

若要在外面透過 Apple「家庭」App 控制 HomeKit，通常需要 HomePod 或 Apple TV 作為家庭中樞。HomeKit 與 VPS 監控本身是兩件事，不影響 Home Assistant 的主要功能。

進階設定可參考：

- [Home Assistant HomeKit Bridge 官方說明](https://www.home-assistant.io/integrations/homekit/)
- [Apple 家庭中樞說明](https://support.apple.com/102557)

## 🔒 安全提醒

- 不要把 MQTT `1883` 直接開放到公網。
- 不要把 MQTT 密碼、Token 或 `/etc/vps-monitor.env` 貼到公開場所。
- 建議透過 Tailscale 存取 Home Assistant。
- 與其他服務共用 VPS 時，請避免占用相同的 TCP 連接埠。
- 安全問題請先閱讀 [SECURITY.md](SECURITY.md)。

## 進階文件

- [MQTT 與 Home Assistant 完整部署](docs/mqtt-vps-setup.md)
- [Tailscale Serve 連接埠衝突紀錄](docs/development-log-tailscale-serve-port-conflict.md)
- [版本更新紀錄](CHANGELOG.md)
- [參與開發](CONTRIBUTING.md)

## 授權

本專案採用 [MIT License](LICENSE)。
