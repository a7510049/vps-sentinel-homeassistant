# 🛡️ VPS Sentinel for Home Assistant

> 把遠方 VPS 的狀態，變成手機裡一眼就看得懂的 Home Assistant 儀表板。

VPS 常常安靜地待在遙遠的機房裡，替我們跑網站、容器、自動化、代理與各種服務。
但當 CPU 爆滿、磁碟快用完、Docker 掉線，或系統需要重新啟動時，它通常不會主動告訴你。

**VPS Sentinel** 透過 MQTT 將 Linux 主機狀態送進 Home Assistant，讓你不用一直登入 SSH，也能隨時查看 VPS 是否健康、服務是否正常，以及有沒有需要處理的事情。

---

## 🌟 你可以用它做什麼

### 📊 即時掌握 VPS 狀態

- CPU、記憶體與磁碟使用率
- 主機在線狀態與最後回報時間
- 作業系統、主機名稱、供應商與地理資訊
- Ubuntu 安全更新與重新啟動需求
- Docker 容器運作狀態
- 指定 systemd 服務健康狀態

所有感測器都會透過 **MQTT Discovery** 自動出現在 Home Assistant，不需要逐一手動建立。

### 🍎 Apple 風格儀表板

專案內建自訂 Home Assistant 卡片，將冷冰冰的伺服器數據整理成更適合日常查看的介面：

- 手機、平板與桌面自適應排版
- 深色與淺色模式
- 清楚的健康狀態與異常提示
- 流暢的觸控與展開效果
- 不依賴 HACS，安裝後即可使用

### 📱 隨時從手機查看

搭配 Home Assistant Companion App 與 Tailscale，即使人在外面，也能透過私有連線安全查看 VPS。

不需要把 Home Assistant 管理介面直接暴露到公網，也不需要在家裡額外準備一台長時間開機的電腦。

### 🧰 繁體中文維護中心

安裝完成後，只要執行：

```bash
sudo vps-sentinel
```

就能進入繁體中文維護中心，集中處理：

- 查看系統與服務狀態
- 修改監控設定
- 建立或套用儀表板
- 執行健康檢查與自動修復
- 備份重要設定
- 更新 VPS Sentinel
- 更新 Home Assistant
- 完整移除專案

### 🛟 安全更新與失敗回復

重要操作不應該靠運氣。

VPS Sentinel 在更新前會備份必要檔案，更新失敗時可自動回復原本版本，並保留最近一份可用備份，避免暫存檔越堆越多。

### 🔐 可選的遠端維護

需要時，可以從 Home Assistant 執行有限度的 VPS 維護操作：

- 檢查可用更新
- 安裝 Ubuntu 安全更新
- 排程重新啟動 VPS

遠端維護預設關閉，而且只允許預先定義的白名單操作，不接受任意 Shell 指令。每次操作都需要確認，並具備過期檢查、重複指令防護、工作鎖與冷卻時間。

---

## 🪶 適合小型 VPS

VPS Sentinel 以低資源占用為設計方向，適合：

- 免費方案 VPS
- 低規格雲端主機
- 個人網站或自架服務
- Docker 與自動化主機
- 想用 Home Assistant 集中查看伺服器狀態的人

Home Assistant、Mosquitto 與 VPS Sentinel 可以安裝在同一台 VPS 上。

---

## 🖥️ 支援環境

| 系統 | 支援程度 |
| --- | --- |
| Ubuntu 22.04／24.04 LTS | ✅ 正式支援 |
| Debian 12／13 | 🧪 實驗性支援 |
| 其他 Linux 發行版 | ❌ 尚未支援 |
| Windows／macOS | ❌ 不支援 |

建議條件：

- `x86_64` 或 `arm64`
- 可使用 `sudo` 的帳號
- 約 1 GB 以上可用記憶體
- 可正常使用 Docker 與 Tailscale

---

## 🚀 快速安裝

在 VPS 執行：

```bash
git clone https://github.com/a7510049/vps-sentinel-homeassistant.git
cd vps-sentinel-homeassistant
sudo bash setup.sh
```

繁體中文安裝器會協助完成：

1. Mosquitto MQTT Broker
2. Home Assistant Container
3. Tailscale 私有連線
4. VPS Sentinel 監控服務
5. 維護工具與儀表板元件

安裝完成後，在 Home Assistant 加入 MQTT 整合，再套用 Apple 風格儀表板：

```bash
sudo vps-sentinel-apple --apply
```

完整安裝說明請參考：

📖 [MQTT 與 Home Assistant 完整安裝教學](docs/mqtt-vps-setup.md)

---

## 🧭 常用指令

| 功能 | 指令 |
| --- | --- |
| 開啟維護中心 | `sudo vps-sentinel` |
| 查看目前狀態 | `sudo vps-sentinel status` |
| 修改監控設定 | `sudo vps-sentinel settings` |
| 重新建立儀表板 | `sudo vps-sentinel dashboard` |
| 健康檢查與修復 | `sudo vps-sentinel doctor` |
| 建立設定備份 | `sudo vps-sentinel backup` |
| 更新 VPS Sentinel | `sudo vps-sentinel upgrade` |
| 更新 Home Assistant | `sudo vps-sentinel ha-update` |
| 查看所有指令 | `sudo vps-sentinel help` |

---

## 🧩 專案組成

- 🐍 **Python Monitor**：收集 VPS 狀態並透過 MQTT 發布
- 🏠 **Home Assistant**：顯示感測器、通知與維護操作
- 🍎 **自訂儀表板卡片**：提供適合手機查看的 Apple 風格介面
- 🐳 **Docker Compose**：部署 Home Assistant Container
- 🛠️ **Shell 維護工具**：安裝、更新、備份、診斷與移除
- 🔒 **Tailscale**：提供私有、安全的遠端存取方式

### 📁 檔案樹

```text
.
├── setup.sh                         # 一條龍安裝入口
├── scripts/                         # 維護、更新、備份與移除工具
│   ├── manage.sh                    # 繁體中文維護中心
│   ├── doctor.sh                    # 健康檢查與修復
│   ├── backup.sh                    # 設定備份與還原
│   ├── automations.sh               # Home Assistant 自動化藍圖管理
│   ├── apple-dashboard.sh           # Apple 風格儀表板安裝器
│   ├── update.sh                    # Home Assistant 更新工具
│   ├── upgrade.sh                   # VPS Sentinel 升級工具
│   └── uninstall.sh                 # 安全移除工具
├── vps-monitor/                     # VPS 狀態收集與 MQTT 發布服務
│   ├── vps_monitor.py
│   ├── vps-monitor.service
│   ├── requirements.txt
│   └── install.sh
├── home-assistant/                  # Home Assistant 前端與自動化資源
│   ├── blueprints/
│   └── www/
│       └── vps-sentinel-apple-card.js
├── docs/                            # 安裝與使用說明
│   └── mqtt-vps-setup.md
├── tests/                           # Python 與指令介面測試
├── .github/workflows/
│   └── validate.yml                 # 自動語法、測試與路徑檢查
├── VERSION                          # 專案版本
└── CHANGELOG.md                     # 完整更新紀錄
```

---

## 💙 設計理念

VPS Sentinel 不只是把數字搬進 Home Assistant。

它希望做到的是：

- 正常時保持安靜
- 出問題時清楚提醒
- 日常操作簡單直覺
- 高風險功能預設關閉
- 更新前可備份，失敗時能回復
- 即使不熟悉 Linux，也能看懂 VPS 現在好不好

讓遠方那台安靜運轉的 VPS，也能在你的手機裡，好好地說一聲：**「我沒事。」** 💚
