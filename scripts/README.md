# 🛠️ 維護腳本

這個目錄集中存放 VPS Sentinel 的維護、診斷、備份、升級與 Home Assistant 操作工具，讓專案根目錄只保留主要入口與文件。

一般使用者仍從根目錄的 `setup.sh` 開始安裝。安裝完成後，建議統一使用 `sudo vps-sentinel [指令]`，不需要進入專案目錄或直接執行這裡的腳本。

| 腳本 | 系統指令 | 用途 |
| --- | --- | --- |
| `manage.sh` | `sudo vps-sentinel` | 維護中心與統一指令入口 |
| `doctor.sh` | `sudo vps-sentinel doctor` | 健康檢查與診斷 |
| `backup.sh` | `sudo vps-sentinel backup` | 備份、還原與保留策略 |
| `automations.sh` | 維護中心選單 | Home Assistant 藍圖管理 |
| `apple-dashboard.sh` | `sudo vps-sentinel apple [--apply]` | Apple 風格面板安裝與套用 |
| `update.sh` | `sudo vps-sentinel ha-update` | Home Assistant Container 安全更新 |
| `upgrade.sh` | `sudo vps-sentinel upgrade` | VPS Sentinel 正式版本升級 |
| `uninstall.sh` | `sudo vps-sentinel-uninstall` | 安全移除工具 |

## 🔄 兩種更新不要混用

- `upgrade` 更新 VPS Sentinel 的監控程式、維護工具與前端元件。
- `ha-update` 更新 Home Assistant Container 映像。

所有維護腳本都只保留在本目錄，專案根目錄不再放置重複入口或相容連結。
