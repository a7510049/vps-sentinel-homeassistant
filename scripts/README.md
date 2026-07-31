# 維護腳本

這個目錄集中存放 VPS Sentinel 的維護、診斷、備份、升級與 Home Assistant 操作工具，讓專案根目錄只保留主要入口與文件。

一般使用者仍從根目錄的 `setup.sh` 開始安裝。安裝完成後，這些腳本會被部署成既有的 `/usr/local/sbin/vps-sentinel-*` 指令，因此日常操作方式不變。

| 腳本 | 用途 |
| --- | --- |
| `manage.sh` | 維護中心與指令入口 |
| `doctor.sh` | 健康檢查與診斷 |
| `backup.sh` | 備份、還原與保留策略 |
| `automations.sh` | Home Assistant 藍圖管理 |
| `apple-dashboard.sh` | Apple 風格面板安裝 |
| `update.sh` | Home Assistant 容器更新 |
| `upgrade.sh` | VPS Sentinel 版本升級 |
| `uninstall.sh` | 安全移除工具 |
