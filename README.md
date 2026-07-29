# 🖥️ VPS Sentinel for Home Assistant

> 把 VPS 的健康狀態帶進 Home Assistant

VPS Sentinel 是一套輕量、可自架的 VPS 監控工具。它會透過 MQTT
Discovery，自動把 CPU、記憶體、磁碟、服務與 Docker 狀態加入
Home Assistant，讓你用熟悉的儀表板查看主機狀況，並在異常時收到通知。

整套系統以安全預設值與低資源占用為設計重點，適合免費或小型 VPS。
HomeKit 整合則保留為選配功能。即使沒有 HomePod 或 Apple TV，也不影響
Home Assistant 儀表板與 Companion App 推播。

## 🧩 支援環境

專案以 Ubuntu LTS VPS 為主要部署環境。為了讓安裝、服務管理與後續
更新維持一致，目前的支援範圍如下：

| 平台 | 支援等級 | 說明 |
| --- | --- | --- |
| Ubuntu 22.04 LTS、24.04 LTS | ✅ 正式支援 | 建議使用，安裝流程與文件均以此環境為基準 |
| Debian 12、13 | 🧪 實驗性支援 | 核心架構相容，但不同套件版本可能需要個別調整 |
| 其他 Ubuntu／Debian 版本 | ⚠️ 盡力支援 | 安裝器可嘗試執行，但不保證所有套件與設定相容 |
| RHEL、Rocky Linux、AlmaLinux、Alpine、Arch Linux | ❌ 不支援 | 套件管理、服務管理或設定路徑不同 |
| Windows、macOS | ❌ 不支援 | 監控程式與安裝器依賴 Linux 系統介面 |

一條龍安裝器需要 `apt`、systemd、`/proc`、root 權限及可使用的 Docker
環境，目前面向一般 `x86_64` 或 `arm64` Linux VPS。容器內執行、
精簡映像、WSL 及已停止安全維護的作業系統不在支援範圍內。

正式支援的平台會優先處理可重現的相容性問題。實驗性支援代表核心
架構可運行，但部署前仍建議先建立 VPS 快照或備份。

## 🚀 快速開始

如果要把 Mosquitto、Home Assistant 與 VPS Monitor 全部部署在同一台
Ubuntu VPS，只要複製並執行這一行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash setup.sh
```

安裝器會以中文引導，並自動完成：

- ✅ 安裝 Tailscale、Mosquitto、Docker、Home Assistant 與 VPS Monitor。
- ✅ 產生兩組不同的 MQTT 高強度密碼。
- ✅ 將 MQTT 限制在 `127.0.0.1`，不公開至網際網路。
- ✅ 優先透過 Tailscale Serve 提供 tailnet 私有 HTTPS。
- ✅ 備份既有 Mosquitto 設定並保留 Home Assistant 資料。
- ✅ 設定開機自動啟動並逐項檢查服務。

過程中只需要選擇「VPS 顯示名稱」與「資源模式」。全新 VPS 需在
瀏覽器授權一次 Tailscale。安裝完成後，再依畫面提示建立 Home Assistant
管理員並加入 MQTT 整合即可。

> 安裝器不修改 UFW、雲端防火牆或 3X-UI 連接埠。
> 若 tailnet 尚未啟用 HTTPS，Tailscale 可能會要求你在瀏覽器確認一次。

## 📊 可以監控什麼

Home Assistant 會自動建立以下資訊：

- CPU、記憶體、根目錄磁碟使用率
- 1 / 5 / 15 分鐘系統負載
- 開機時間與運行時間
- 網路上傳／下載速率
- 可安裝安全更新數量
- Docker 運行中與異常容器數，主機已安裝 Docker 時才會顯示

可用於自動化與通知的狀態：

- `連線狀態`：監控程式停止或 VPS 失聯時顯示問題
- `系統負載狀態`：CPU ≥ 90%、RAM ≥ 90%，連續約 5 分鐘時顯示問題
- `磁碟空間狀態`：根目錄使用率 ≥ 85% 時顯示問題
- `服務運作狀態`：指定的 systemd 服務停止，或 Docker 有 unhealthy /
  restarting 容器
- `重新啟動提醒`：Ubuntu 建立 `/var/run/reboot-required` 時顯示問題

告警門檻都能在環境檔中調整，不需要修改程式。
當安全更新或 Docker 狀態暫時無法讀取時，實體會顯示「未知」，不會
以 `0` 冒充正常結果。

## 🔌 接到既有的 Home Assistant

如果 Home Assistant、Mosquitto 與本監控程式都部署在同一台 Ubuntu
VPS，可參考完整中文指南：

**[Ubuntu VPS：Mosquitto + Home Assistant Container 完整中文部署指南](docs/mqtt-vps-setup.md)**

在 Home Assistant 的「設定 → 裝置與服務」加入 MQTT。若是 Home
Assistant OS，可安裝官方 Mosquitto broker 附加元件，並建立一個專用
MQTT 使用者。記下 broker 的區網位址、連接埠、帳號及密碼。

VPS 必須能主動連到 broker，但不需要把 VPS 的任何連接埠公開到網際網路。
若 broker 不在 VPN / 私網內，務必使用 TLS，不要將未加密的 1883
直接開放到公網。

## 🛠️ 只安裝 VPS Monitor

如果已經有可用的 Home Assistant 與 MQTT broker，只需要安裝監控程式：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && sudo bash vps-sentinel-homeassistant/vps-monitor/install.sh
```

安裝器會依序詢問 MQTT 位址、TLS、帳密、VPS 名稱、要監控的 systemd
服務與告警門檻，接著自動：

1. 安裝 Python、虛擬環境與 CA 憑證。
2. 以權限 `600` 建立 `/etc/vps-monitor.env`。
3. 安裝並啟用 `vps-monitor.service`。
4. 檢查服務，失敗時直接顯示最近 30 行日誌。

重新執行安裝器時，可以沿用現有設定，或先自動備份再重新設定。
若 Python 依賴沒有變更，更新時會略過虛擬環境重建，只替換程式並
重新啟動服務。

安裝時可選擇資源模式：

| 模式 | 數值回報 | 服務／Docker 檢查 | 更新檢查 | 網路速率預設 |
| --- | ---: | ---: | ---: | --- |
| 極省資源 | 5 分鐘 | 15 分鐘 | 24 小時 | 關閉 |
| 平衡（推薦） | 2 分鐘 | 5 分鐘 | 24 小時 | 關閉 |
| 即時監控 | 30 秒 | 1 分鐘 | 6 小時 | 開啟 |

不論選擇哪個模式，MQTT 都維持長連線，因此 VPS 或監控程式斷線時，
仍會透過 Last Will 立即更新「連線狀態」。

若 Mosquitto 因更新或重新啟動而短暫中斷，監控程式會在背景以最長
5 分鐘的退避間隔持續重連，不會退出或形成快速重啟循環。重新連線後
會自動恢復 Discovery、上線狀態與數值回報。

手動檢查：

```bash
systemctl status vps-monitor
journalctl -u vps-monitor -f
```

成功後，Home Assistant 的 MQTT 整合下會自動出現 VPS 裝置。

## 🔄 安全更新 Home Assistant

一條龍安裝完成後，可使用以下指令檢查並更新 Home Assistant：

```bash
sudo vps-sentinel-update
```

更新工具會先驗證 Home Assistant 設定，再比較容器映像。只有發現新版
時才會建立設定備份並更新。啟動檢查失敗時會自動退回原本映像，備份
則保留在 `/opt/homeassistant-backups`。為節省磁碟空間，只保留最近
三份自動備份。

重新執行 `setup.sh` 不會再自動拉取新版 Home Assistant，避免維護監控
設定時意外升級。

## 🍎 選配：加入 HomeKit

> [!IMPORTANT]
> HomeKit 是選配功能，不影響 Home Assistant 儀表板與手機推播。
> iPhone 必須能在相同區域網路找到 Home Assistant Bridge 才能完成
> 初次配對。Tailscale 通常不會轉送 HomeKit 使用的 mDNS 廣播。若
> Home Assistant 位於遠端 VPS，可能需要額外配置 mDNS reflector 與
> `advertise_ip`，本安裝器不會自動變更這類網路設定。
>
> 只有 iPhone 並不等於具備家庭中樞。離家控制、共享家庭及 Apple
>「家庭」自動化需要 HomePod 或 Apple TV 擔任家庭中樞。沒有家庭中樞
> 時，建議直接使用 Home Assistant App 查看狀態與接收推播通知。
>
> 參考：[Apple 家庭中樞說明](https://support.apple.com/102557)、
> [Home Assistant HomeKit Bridge 網路需求](https://www.home-assistant.io/integrations/homekit/)

先將 [home-assistant/vps_homekit.yaml](home-assistant/vps_homekit.yaml)
複製到 Home Assistant 設定目錄，並在 `configuration.yaml` 加入：

```yaml
homekit: !include vps_homekit.yaml
```

重新啟動 Home Assistant，從通知取得配對碼，於 Apple「家庭」加入
「Home Assistant VPS」橋接器。若你已用 UI 建立 HomeKit Bridge，
不要再建立 YAML bridge。請改到該 bridge 的「設定」中，選取下列五個
`binary_sensor.vps_*` 實體即可。

> 實體 ID 是首次建立時決定的。如果名稱曾被占用，Home Assistant
> 可能加上 `_2`。此時請依 UI 中的實際實體 ID 修改 YAML。

## ✅ 測試告警

可安全地停止監控程式測試離線狀態：

```bash
sudo systemctl stop vps-monitor
```

MQTT 的 Last Will 會立即將「連線狀態」切換為問題。測試完成後執行：

```bash
sudo systemctl start vps-monitor
```

若已配置家庭中樞，可在 Apple「家庭」中針對五個狀態感測器設定
自動化與活動通知。沒有家庭中樞時，請使用 Home Assistant 自動化搭配
Companion App 推播。

## 🔒 安全性

- 不要將未加密的 MQTT `1883` 連接埠公開至網際網路。
- 帳密只會儲存在 VPS 本機、僅限 root 讀取的設定檔，不應提交至 Git。
- 正式環境執行前，建議先閱讀 [安全政策](SECURITY.md)。
- 發現安全問題時，請勿建立公開 Issue。請依安全政策私下回報。

## 🤝 授權與貢獻

本專案採用 [MIT License](LICENSE)。歡迎回報問題、改善文件或協助測試
其他平台。提交變更前請先閱讀 [貢獻指南](CONTRIBUTING.md)。
