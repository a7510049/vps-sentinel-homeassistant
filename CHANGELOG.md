# 更新紀錄

## 0.2.0

- Home Assistant 改用 Tailscale Serve 提供 tailnet 私有 HTTPS
- 新增設定驗證、備份、啟動檢查與映像回退的更新工具
- 監控程式更新時略過未變更的 Python 依賴，並確保服務重新啟動
- 無法讀取安全更新或 Docker 狀態時改為顯示未知
- Debian 裝置顯示實際的作業系統名稱
- CI 新增完整 ShellCheck、Python 單元測試與 Dependabot

## 0.1.0

- 首次公開版本
- 提供中文一條龍安裝
- 整合 MQTT Discovery、Home Assistant 與選配 HomeKit
- 提供低資源監控模式與 MQTT 自動重連
