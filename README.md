# VPS Sentinel for Home Assistant

> 讓遠方那台安靜運轉的 VPS，也能在你的手機裡，好好地說一聲：「我沒事。」

我們把很多重要的東西交給 VPS：網站、服務、自動化、代理、容器，以及一些只有自己知道用途的小宇宙。

但它通常住在遙遠的機房裡。沒有螢幕、沒有聲音，也不會在快撐不住時主動敲你的門。

**VPS Sentinel** 想做的事情很簡單：把冷冰冰的 Linux 狀態，整理成一個在 Home Assistant 裡看得懂、碰得到，也願意每天打開看的儀表板。

CPU 忙不忙、記憶體夠不夠、磁碟是不是快滿了、Docker 有沒有掉線、安全更新該不該處理——不用再登入 SSH 後逐條下指令。拿起手機，就能知道遠方那台機器今晚是否安好。

---

## 它會替你守著什麼

VPS Sentinel 透過 MQTT，把主機狀態自動送進 Home Assistant：

- CPU、記憶體與磁碟使用率
- 主機是否在線，以及資料是否持續回報
- Ubuntu 是否有安全更新或需要重新啟動
- Docker 容器與指定 systemd 服務是否正常
- VPS 所在國家、供應商與作業系統資訊
- 可選的安全維護操作：檢查更新、安裝安全更新、排程重新啟動

感測器會透過 MQTT Discovery 自動建立，不必一顆一顆手動設定。

而它不只想「顯示數字」。儀表板會把真正需要注意的事情放到你眼前；正常時保持安靜，出問題時才認真提醒。

## 你會得到的體驗

- 🍎 **Apple 風格自適應面板**：手機、平板與桌面都能自然排列
- 🌗 **深色與淺色模式**：跟著 Home Assistant 外觀切換
- ✨ **細緻觸控回饋**：不是必要，但每天看的東西值得舒服一點
- 🪶 **低資源占用**：適合免費方案與小型 VPS
- 🔒 **預設不暴露管理介面**：推薦使用 Tailscale 私有連線
- 🧰 **繁體中文維護中心**：日常檢查、更新、備份與移除集中處理
- 🛟 **更新前備份與失敗回復**：重要操作不應該靠運氣
- 🧩 **不依賴 HACS**：Apple 面板為專案自帶元件，另保留原生備援面板

---

## 先看看它適不適合你

### 建議環境

- Ubuntu 22.04 LTS 或 24.04 LTS
- `x86_64` 或 `arm64` VPS
- 可使用 `sudo` 的帳號
- 至少保留約 1 GB 可用記憶體

| 系統 | 支援程度 |
| --- | --- |
| Ubuntu 22.04／24.04 LTS | ✅ 正式支援 |
| Debian 12／13 | 🧪 可測試使用 |
| 其他 Linux 發行版 | ❌ 目前不支援 |
| Windows／macOS | ❌ 不支援 |

> Home Assistant、Mosquitto 與 VPS Sentinel 可以住在同一台 VPS。家裡不需要另外準備一台永遠不能關機的電腦。

---

## 第一次安裝

在 Ubuntu VPS 貼上這一行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git && cd vps-sentinel-homeassistant && sudo bash setup.sh
```

安裝器會以繁體中文陪你完成：

1. Mosquitto MQTT
2. Home Assistant Container
3. Tailscale 安全連線
4. VPS Sentinel 監控服務
5. Home Assistant 儀表板

大多數使用者直接採用推薦選項即可。完成後，畫面會留下 Home Assistant 網址、MQTT 帳號與下一步操作。

### 安裝後，還差兩個小步驟

#### 1. 在 Home Assistant 加入 MQTT

前往：

**設定 → 裝置與服務 → 新增整合 → MQTT**

同機安裝通常填寫：

```text
Broker：127.0.0.1
Port：1883
Username：home-assistant
Password：安裝時設定的密碼
TLS：關閉
```

完成後，VPS Sentinel 裝置與感測器會自動出現。

需要完整逐步說明時，請看：

**[MQTT 與 Home Assistant 完整安裝教學](docs/mqtt-vps-setup.md)**

#### 2. 套用 Apple 風格儀表板

```bash
sudo vps-sentinel-apple --apply
```

重新整理 Home Assistant 後，你會看到 CPU、記憶體、磁碟、主機資訊與健康狀態。

若畫面仍停留在舊版，請確認前端資源網址為：

```text
/local/vps-sentinel-apple-card.js?v=0.9.6
```

---

## 手機就是它最自然的家

1. 安裝 Home Assistant Companion App。
2. 手機開啟 Tailscale，登入與 VPS 相同的帳號。
3. 在 App 加入安裝器顯示的 Home Assistant 網址。

從此，VPS 在哪個國家不重要。只要它仍連著網路，你就能在手掌裡看見它。

目前預設以 Tailscale 保護 Home Assistant，因此人在外面時也需要開啟 Tailscale。多一步連線，換來的是不必把管理介面赤裸地公開到網際網路。

---

## 日常相處方式

平常只要執行：

```bash
sudo vps-sentinel
```

就會開啟繁體中文維護中心。

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

### 更新 VPS Sentinel

```bash
sudo vps-sentinel upgrade
sudo vps-sentinel-apple --apply
```

### 更新 Home Assistant

```bash
sudo vps-sentinel ha-update
```

更新前會備份必要內容，成功後也會清理不再需要的暫存備份，避免時間久了留下一座考古遺址。

---

## 遠端維護：能力越大，確認框越多

儀表板可以選擇顯示：

- 檢查可用更新
- 安裝 Ubuntu 安全更新
- 排程重新啟動 VPS

這些功能**預設關閉**。需要時執行：

```bash
sudo vps-sentinel settings
```

再開啟「Home Assistant 遠端維護」。

安全設計包含：

- 只允許三種預先定義的操作
- 不接受任意 Shell 指令
- 每次操作都要再次確認
- 過期或重複的 MQTT 指令會被拒絕
- 操作具有單一工作鎖與冷卻時間
- 維護工作由獨立 systemd 暫時服務執行

只想安靜監控也完全沒問題。讓遠端維護保持關閉，就是最保守也最省心的設定。

---

## 當它看起來不太對勁

先執行：

```bash
sudo vps-sentinel doctor
```

它會檢查 VPS Sentinel、Mosquitto、Home Assistant、Docker、Tailscale、磁碟空間與設定檔。

查看即時監控日誌：

```bash
sudo journalctl -u vps-monitor -f
```

查看 Home Assistant 日誌：

```bash
sudo docker logs homeassistant --tail 100
```

### 所有卡片突然顯示「不可用」

通常是 MQTT 或監控服務剛重新啟動。先等約一分鐘，再執行：

```bash
sudo systemctl restart mosquitto vps-monitor
```

仍未恢復時，再交給 `sudo vps-sentinel doctor` 檢查。

---

## 備份與道別

建立設定備份：

```bash
sudo vps-sentinel backup
```

備份預設存放於：

```text
/opt/vps-sentinel-backups
```

完整移除：

```bash
sudo vps-sentinel-uninstall
```

移除器會先列出選項，不會一聲不響地帶走 Home Assistant、Mosquitto、Docker 或 Tailscale。只有在你明確選擇後，才會處理相關元件。

---

## HomeKit 是加分題，不是入場券

沒有 HomePod 或 Apple TV，仍可正常使用：

- Home Assistant 儀表板
- Companion App
- 手機通知
- Tailscale 遠端連線

若希望人在外面時透過 Apple「家庭」App 控制 HomeKit，通常需要 HomePod 或 Apple TV 作為家庭中樞。這與 VPS Sentinel 的主要監控功能彼此獨立。

進階設定：

- [Home Assistant HomeKit Bridge 官方說明](https://www.home-assistant.io/integrations/homekit/)
- [Apple 家庭中樞說明](https://support.apple.com/102557)

---

## 它目前還不完美

這是一個正在長大的專案。以下不是藏在地毯下的祕密，而是目前已知的限制與改善方向：

### 1. 安裝流程仍有一小段需要手動完成

安裝器可以建立 MQTT 與 Home Assistant 環境，但第一次仍需進入 Home Assistant 手動加入 MQTT 整合。對熟悉 Home Assistant 的人很簡單，對第一次接觸的人則可能稍微迷路。

### 2. 前端快取版本仍需與程式版本同步

Home Assistant App 對自訂前端資源的快取相當頑固。Apple 面板更新後，需要同步調整資源網址的 `?v=` 版本，否則可能看見舊畫面。這也是 README 曾經落後於實際版本的原因。

### 3. Tailscale Serve 可能與既有的 443 服務衝突

如果 VPS 已經有 Nginx、Caddy、面板或其他程式占用 HTTPS 連接埠，Tailscale Serve 的設定需要另外協調。安裝器不會擅自修改既有服務的連接埠。

詳情請看：[Tailscale Serve 連接埠衝突紀錄](docs/development-log-tailscale-serve-port-conflict.md)。

### 4. 正式測試範圍仍以 Ubuntu 為主

Debian 12／13 可以測試，但尚未承諾與 Ubuntu 相同的完整相容性。其他 Linux 發行版目前也沒有正式支援，跨發行版安裝仍是未來工作。

### 5. 遠端維護刻意做得保守

目前只允許三種白名單操作，不能從 Home Assistant 自訂任意維護指令。這不是功能做不出來，而是安全上的主動取捨；未來若擴充，也必須維持可審核、可確認、可回復的原則。

### 6. 文件與版本發布流程還能更自動化

README、前端資源版本與 CHANGELOG 目前仍可能因人工更新而短暫不同步。理想狀態是由發布流程自動檢查版本一致性，避免一個數字躲在角落裡偷偷落隊。

### 7. 專案協作文件仍在整理

提交紀錄中曾出現 `CONTEXT.md` 與 `BACKLOG.md`，但目前預設分支未保留這兩份檔案。後續會重新建立清楚的開發脈絡、待辦方向與版本規劃，讓貢獻者不用靠考古理解專案。

如果你遇到新的問題，歡迎提交 Issue。請避免附上 MQTT 密碼、Token、公網 IP 或 `/etc/vps-monitor.env` 的完整內容。

---

## 安全底線

- 不要把 MQTT `1883` 直接開放到公網
- 不要公開 MQTT 密碼、Token 或 `/etc/vps-monitor.env`
- 建議透過 Tailscale 存取 Home Assistant
- 與其他服務共用 VPS 時，先確認 TCP 連接埠是否衝突
- 發現安全問題時，請先閱讀 [SECURITY.md](SECURITY.md)

---

## 更多文件

- [MQTT 與 Home Assistant 完整部署](docs/mqtt-vps-setup.md)
- [Tailscale Serve 連接埠衝突紀錄](docs/development-log-tailscale-serve-port-conflict.md)
- [版本更新紀錄](CHANGELOG.md)
- [參與開發](CONTRIBUTING.md)

## 授權

本專案採用 [MIT License](LICENSE)。

---

<p align="center">
  <strong>遠方的機器不會說話，但至少，我們可以讓它被好好看見。</strong>
</p>
