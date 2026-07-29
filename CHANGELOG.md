# 更新紀錄

## 0.2.1

- 新增中文互動式移除工具，可選擇只移除監控器或完整清除專案環境
- 完整移除預設先建立最終備份，並以指定確認文字避免誤刪
- 只移除專案專用的 MQTT 帳號、設定、Tailscale Serve 與固定路徑
- 共用套件採保守偵測與二次確認，保護其他 MQTT、Docker 與 SSH 用途

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
