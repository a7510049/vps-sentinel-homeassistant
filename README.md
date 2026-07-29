# VPS Sentinel for Home Assistant

> 輕量、安全、可自架的 VPS 狀態監控與選配 HomeKit 告警方案

透過 MQTT Discovery 將 VPS 的資源、服務與 Docker 狀態整合至
Home Assistant，並透過 HomeKit Bridge 將重要異常同步至 Apple「家庭」。

## 平台相容性

本專案以 Ubuntu LTS VPS 為主要開發與部署環境。為確保一鍵安裝、
服務管理及後續更新行為一致，支援範圍定義如下：

| 平台 | 支援等級 | 說明 |
| --- | --- | --- |
| Ubuntu 22.04 LTS、24.04 LTS | 正式支援 | 建議使用；安裝流程與文件均以此環境為基準 |
| Debian 12、13 | 實驗性支援 | 核心架構相容，但不同套件版本可能需要個別調整 |
| 其他 Ubuntu／Debian 版本 | 盡力支援 | 安裝器可嘗試執行，但不保證所有套件與設定相容 |
| RHEL、Rocky Linux、AlmaLinux、Alpine、Arch Linux | 不支援 | 套件管理、服務管理或設定路徑不同 |
| Windows、macOS | 不支援 | 監控程式與安裝器依賴 Linux 系統介面 |

一條龍安裝器需要 `apt`、systemd、`/proc`、root 權限及可使用的 Docker
環境。目前面向一般 `x86_64` 或 `arm64` Linux VPS；容器內執行、
精簡映像、WSL 及已停止安全維護的作業系統不在支援範圍內。

「正式支援」代表專案會優先修正可重現的相容性問題；「實驗性支援」
代表架構上可運行，但部署前仍建議先建立 VPS 快照或備份。

## 最簡單：一條龍安裝

適用於 Mosquitto、Home Assistant 與 VPS Monitor 都放在同一台 Ubuntu
VPS 的使用方式。公開版本不需要 GitHub 帳號或 Deploy key，整行複製
執行即可：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash setup.sh
```

中文安裝器會自動完成：

- 安裝 Tailscale、Mosquitto、Docker、Home Assistant 與 VPS Monitor。
- 產生兩組不同的 MQTT 高強度密碼。
- 將 MQTT 限制在 `127.0.0.1`，不公開至網際網路。
- 備份既有 Mosquitto 設定並保留 Home Assistant 資料。
- 設定開機自動啟動並逐項檢查服務。

你只需回答「VPS 顯示名稱」及「資源模式」。全新 VPS 還需要在瀏覽器
授權一次 Tailscale。最後仍有兩個無法代替你的畫面操作：建立 Home
Assistant 管理員，以及在 Home Assistant 新增 MQTT 整合。安裝器會在
完成畫面直接顯示網址與需要填入的內容。

> 安裝器不修改 UFW、雲端防火牆或 3X-UI 連接埠。

## 監控項目

Home Assistant 數值：

- CPU、記憶體、根目錄磁碟使用率
- 1 / 5 / 15 分鐘系統負載
- 開機時間與運行時間
- 網路上傳／下載速率
- 可安裝安全更新數量
- Docker 運行中、異常容器數（主機有 Docker 時）

選配的 HomeKit 狀態：

- `VPS 離線`：監控程式停止或 VPS 失聯
- `VPS 資源過載`：CPU ≥ 90%、RAM ≥ 90%，連續約 5 分鐘
- `VPS 磁碟不足`：根目錄使用率 ≥ 85%
- `VPS 服務異常`：指定的 systemd 服務停止，或 Docker 有 unhealthy /
  restarting 容器
- `VPS 需要重啟`：Ubuntu 建立 `/var/run/reboot-required`

所有門檻都能在環境檔調整。

## 1. 準備 MQTT

如果 Home Assistant、Mosquitto 與本監控程式都部署在同一台 Ubuntu
VPS，請直接參考：

**[Ubuntu VPS：Mosquitto + Home Assistant Container 完整中文部署指南](docs/mqtt-vps-setup.md)**

在 Home Assistant 的「設定 → 裝置與服務」加入 MQTT。若是 Home
Assistant OS，可安裝官方 Mosquitto broker 附加元件，並建立一個專用
MQTT 使用者。記下 broker 的區網位址、連接埠、帳號及密碼。

VPS 必須能主動連到 broker；不需要把 VPS 的任何連接埠公開到網際網路。
若 broker 不在 VPN / 私網內，務必使用 TLS，不要將未加密的 1883
直接開放到公網。

## 2. 中文一鍵安裝

若只需要將監控程式接到既有的 MQTT broker，可執行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && sudo bash vps-sentinel-homeassistant/vps-monitor/install.sh
```

安裝器會以中文依序詢問 MQTT 位址、TLS、帳密、VPS 名稱、要監控的
systemd 服務與告警門檻，接著自動：

1. 安裝 Python、虛擬環境與 CA 憑證。
2. 以權限 `600` 建立 `/etc/vps-monitor.env`。
3. 安裝並啟用 `vps-monitor.service`。
4. 檢查服務；失敗時直接顯示最近 30 行日誌。

重新執行安裝器時，可以沿用現有設定，或先自動備份再重新設定。

安裝時可選擇資源模式：

| 模式 | 數值回報 | 服務／Docker 檢查 | 更新檢查 | 網路速率預設 |
| --- | ---: | ---: | ---: | --- |
| 極省資源 | 5 分鐘 | 15 分鐘 | 24 小時 | 關閉 |
| 平衡（推薦） | 2 分鐘 | 5 分鐘 | 24 小時 | 關閉 |
| 即時監控 | 30 秒 | 1 分鐘 | 6 小時 | 開啟 |

不論選擇哪個模式，MQTT 都維持長連線，因此 VPS 或監控程式斷線時，
仍會透過 Last Will 立即更新「VPS 離線」狀態。
若 Mosquitto 因更新或重新啟動而短暫中斷，監控程式會在背景以最長
5 分鐘的退避間隔持續重連，不會退出或形成快速重啟循環；重新連線後
會自動恢復 Discovery、上線狀態與數值回報。

手動檢查：

```bash
systemctl status vps-monitor
journalctl -u vps-monitor -f
```

成功後，Home Assistant 的 MQTT 整合下會自動出現 VPS 裝置。

## 安全性

- 不要將未加密的 MQTT `1883` 連接埠公開至網際網路。
- 帳密只會儲存在 VPS 本機的 root-only 設定檔，不應提交至 Git。
- 正式環境執行前，建議先閱讀 [安全政策](SECURITY.md)。
- 發現安全問題時，請勿建立公開 Issue；請依安全政策私下回報。

## 授權與貢獻

本專案採用 [MIT License](LICENSE)。錯誤修正、文件改善與平台相容性
回報皆歡迎參與；提交前請閱讀 [貢獻指南](CONTRIBUTING.md)。

## 3. 加入 HomeKit

> [!IMPORTANT]
> HomeKit 是選配功能，不影響 Home Assistant 儀表板與手機推播。
> iPhone 必須能在相同區域網路找到 Home Assistant Bridge 才能完成
> 初次配對；Tailscale 通常不會轉送 HomeKit 使用的 mDNS 廣播。若
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
不要再建立 YAML bridge；改到該 bridge 的「設定」中，選取下列五個
`binary_sensor.vps_*` 實體即可。

> 實體 ID 是首次建立時決定的。如果名稱曾被占用，Home Assistant
> 可能加上 `_2`；此時請依 UI 中的實際實體 ID 修改 YAML。

## 4. 驗證告警

可安全地停止監控程式測試離線狀態：

```bash
sudo systemctl stop vps-monitor
```

MQTT 的 Last Will 會立即將「VPS 離線」切為開啟。測完執行：

```bash
sudo systemctl start vps-monitor
```

若已配置家庭中樞，可在 Apple「家庭」中針對五個狀態感測器設定
自動化與活動通知。沒有家庭中樞時，請使用 Home Assistant 自動化搭配
Companion App 推播。
