# 🖥️ VPS Sentinel for Home Assistant

> 輕量、自架、為小型 VPS 打造的 Home Assistant 主機監控方案

VPS Sentinel 會透過 MQTT Discovery，自動將 VPS 的 CPU、記憶體、
磁碟、服務與 Docker 狀態加入 Home Assistant。你可以在同一個儀表板
掌握主機狀況，並透過 Home Assistant Companion App 接收異常通知。

專案以低資源占用、安全預設值與簡單維護為設計重點，適合免費方案及
小型 Ubuntu VPS。中文安裝器可協助部署 Home Assistant、Mosquitto、
Tailscale 與監控服務；安裝後則可透過單一維護中心管理設定、更新、
儀表板與移除流程。

HomeKit 為選配功能。沒有 HomePod 或 Apple TV 時，Home Assistant
儀表板與 Companion App 推播仍可正常使用。

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

若要在同一台 Ubuntu VPS 部署 Mosquitto、Home Assistant 與 VPS
Sentinel，請執行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash setup.sh
```

安裝器會以中文逐步引導，並自動完成：

- ✅ 安裝 Tailscale、Mosquitto、Docker、Home Assistant 與 VPS Sentinel。
- ✅ 產生兩組不同的 MQTT 高強度密碼。
- ✅ 將 MQTT 限制在 `127.0.0.1`，不公開至網際網路。
- ✅ 優先透過 Tailscale Serve 提供 tailnet 私有 HTTPS。
- ✅ 備份既有 Mosquitto 設定並保留 Home Assistant 資料。
- ✅ 設定開機自動啟動並逐項檢查服務。

安裝過程會請你設定 VPS 顯示名稱並選擇資源模式；全新 VPS 另需在
瀏覽器授權一次 Tailscale。完成後，依畫面提示建立 Home Assistant
管理員並加入 MQTT 整合即可開始使用。

> 安裝器不修改 UFW、雲端防火牆或既有服務的連接埠。
> 若 tailnet 尚未啟用 HTTPS，Tailscale 可能會要求你在瀏覽器確認一次。

## 📊 可以監控什麼

Home Assistant 會自動建立以下資訊：

- CPU、記憶體、根目錄磁碟使用率與實際容量
- 1 / 5 / 15 分鐘系統負載
- 開機時間與運作時間
- 網路上傳／下載速率
- 資料是否持續更新
- 可安裝安全更新數量
- Docker 運作中與異常容器數，主機已安裝 Docker 時才會顯示

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

平衡模式只讓 CPU 與記憶體每 15 秒更新；磁碟、Docker、服務與運作
時間每 5 分鐘檢查，安全更新每日檢查一次。這能保持畫面靈敏，同時
避免在免費 VPS 上反覆執行較重的系統檢查。

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

同一台 VPS 若已有其他服務使用標準 `TCP 443`，可能與 Tailscale
Serve 衝突。請參考
**[開發日誌：Tailscale Serve 與既有服務的 443 連接埠衝突](docs/development-log-tailscale-serve-port-conflict.md)**，
了解症狀、判斷方式及使用 `TCP 8443` 分流的完整紀錄。

## 🛠️ 只安裝 VPS Monitor

如果已經有可用的 Home Assistant 與 MQTT broker，可以只安裝監控程式：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash vps-monitor/install.sh
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
| 極省資源 | 60 秒 | 15 分鐘 | 24 小時 | 關閉 |
| 平衡（推薦） | 15 秒 | 5 分鐘 | 24 小時 | 關閉 |
| 即時監控 | 10 秒 | 1 分鐘 | 6 小時 | 開啟 |

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

## 🧰 中文維護中心

安裝完成後，日常管理只需要一個指令：

```bash
sudo vps-sentinel
```

若是從 `v0.2.x` 或更早版本升級，請先在原本的專案目錄執行一次：

```bash
git pull
sudo bash setup.sh
```

這次執行會安裝新的管理指令並沿用既有資料。完成後，未來即可從維護
中心更新，不必反覆下載或重新安裝整套環境。

維護中心可以：

- 📊 系統總覽：查看監控、MQTT、Docker 與 Home Assistant 狀態
- ⚙️ 監控設定：切換資源模式，調整 CPU、記憶體與磁碟告警門檻
- 🏠 Home Assistant：管理監控面板、自動化模板與安全更新
- 🧰 系統維護：健康檢查、備份還原、版本更新與完整移除

所有子選單都以 `0` 返回上一層，直接按 Enter 會採用畫面標示的預設
選項。完整移除等高影響操作會先說明用途，並在真正刪除前再次確認。

若只想快速查詢或執行特定工具，也可以使用子指令：

```bash
sudo vps-sentinel status
sudo vps-sentinel settings
sudo vps-sentinel doctor
sudo vps-sentinel backup
sudo vps-sentinel upgrade
sudo vps-sentinel help
```

設定變更前會自動備份；若監控服務無法重新啟動，會立即回復原設定。

更新 VPS Sentinel 時，工具只會採用 GitHub 上的最新正式 Release。
下載完成後會檢查版本、必要檔案與基本語法，確認無誤才替換程式；
若新版服務無法正常啟動，會自動回復。也可以直接執行：

```bash
sudo vps-sentinel-upgrade
```

更新 Home Assistant 時，工具會先驗證設定，再比較 Container 映像。
只有發現新版時才會備份並更新；啟動檢查失敗時會自動退回原本映像。
也可以直接執行：

```bash
sudo vps-sentinel-update
```

兩種更新在確認服務恢復後，只保留最近一份專案專用的回復備份；
Home Assistant 更新使用的舊映像標籤也會一併移除，避免長期占用 VPS
磁碟空間。更新失敗時不會提前清理，確保自動回復仍有可用資料。
工具不會執行全域 Docker 清理，也不會刪除其他服務的映像或備份。
重新執行 `setup.sh` 不會自動升級 Home Assistant，避免調整監控設定時
意外變更正在運作的版本。

「建立或更新儀表板」只使用 Home Assistant 內建卡片，不需要 HACS。
自適應版面會在手機改為單欄，在平板與電腦依寬度展開最多三欄；
CPU、記憶體與磁碟使用同級動態長條，異常時才顯示醒目提醒。點選
任一資源卡可直接開啟 Home Assistant 原生詳細資料。

0.8 起另提供可選的 Apple 風格面板。它使用約 10 KB 的本機前端元件，
不需要 HACS、額外主題，也不會建立新的 VPS 常駐程序；外觀會自動跟隨
Home Assistant 的深色或淺色模式。安裝工具會透過官方
儀表板資源頁載入元件；第一次需要手動註冊 JavaScript 模組，後續更新
不必重複新增。註冊後執行 `sudo vps-sentinel-apple --apply` 即可套用。
0.8 系列固定資源網址為 `/local/vps-sentinel-apple-card.js?v=0.8`；
只有未來跨至 0.9 等新版前端時才需要更換一次。
若要返回完全原生的穩定面板，執行 `sudo vps-sentinel dashboard` 即可。
工具會先備份 `configuration.yaml`，產生獨立的
`vps-sentinel-dashboard.yaml`，通過 Home Assistant 設定檢查後才重新
啟動；驗證或啟動失敗時會自動回復原設定。工具不直接修改 `.storage`。

面板可顯示節點國旗、VPS 供應商與作業系統。國家與供應商預設於監控
服務啟動時透過 `https://ipwho.is/` 查詢一次，不會把公網 IP 發布到
MQTT。若不希望使用外部查詢，可在 `/etc/vps-monitor.env` 設定
`IP_METADATA=false` 後重新啟動 `vps-monitor`。

## 🩺 健康檢查與安全修復

健康檢查為按需執行，不會建立新的常駐服務，也不會增加平時的 CPU 或
記憶體用量：

```bash
sudo vps-sentinel-doctor
```

工具會檢查監控程式、MQTT、Docker、Home Assistant、Tailscale、設定檔
權限及磁碟空間。修復操作一律由使用者選擇，不會自行重設帳密、修改
防火牆或重新啟動整台 VPS。

需要回報問題時，可以建立匿名診斷報告。報告只包含版本、系統架構與
檢查結果，不會收集 MQTT 密碼、Token、IP 位址、VPS 名稱或完整日誌。

## 📦 設定備份與還原

從維護中心進入「備份與還原」，或直接執行：

```bash
sudo vps-sentinel-backup
```

設定備份包含 Home Assistant 設定、Compose 檔案及 VPS Sentinel 環境
設定；為控制容量，不包含 Home Assistant 歷史資料庫與日誌。還原前會
再次備份目前狀態，還原後則會驗證監控服務與 Home Assistant 設定。

手動備份預設保存在 `/opt/vps-sentinel-backups`，可由工具保留指定數量。

## 🤖 Home Assistant 自動化模板

VPS Sentinel 內建三組 Blueprint：

- 系統異常通知：監看負載、磁碟與服務狀態，避免短暫尖峰誤報
- 主機離線通知：離線時立即通知，並可設定恢復連線通知
- 每日健康摘要：在指定時間執行自訂摘要通知

從維護中心選擇「Home Assistant 自動化模板」即可安裝。模板只會寫入
Home Assistant 官方 Blueprint 目錄，不修改 `.storage`、既有自動化或
通知設定。安裝後請到「設定 → 自動化與場景 → 藍圖」建立自動化，並
自行選擇 Companion App 或其他通知動作。

## 🧹 安全移除

需要停用或重新部署時，請使用中文移除工具：

```bash
sudo vps-sentinel-uninstall
```

移除前可以選擇範圍：

1. 只移除 VPS Monitor，保留 Home Assistant、MQTT 與 Tailscale。
2. 完整移除本專案建立的 Container、設定、歷史資料、MQTT 專用帳號、
   Tailscale Serve 規則與管理指令。

完整移除需要輸入指定確認文字，並預設先在 `/root` 建立一份最終備份。
Mosquitto、Docker 與 Tailscale 都可能被其他服務共用，因此不會直接
移除：工具只會在確認沒有其他 MQTT 設定或 Docker Container 後，再
個別詢問是否移除套件。Tailscale 一律保留，避免移除過程切斷目前的
SSH 連線。

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
