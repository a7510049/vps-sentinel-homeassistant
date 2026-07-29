# 更新紀錄

## 0.4.0

- 新增按需執行的一鍵健康檢查，不增加常駐監控資源用量
- 新增經使用者確認的安全修復與匿名診斷報告
- 新增更新前磁碟空間及安裝完整性預檢
- 新增輕量設定備份、清單、保留策略與還原驗證
- 新增三組 Home Assistant Blueprint：系統異常、主機離線及每日摘要
- Blueprint 不修改 `.storage`，通知動作由使用者在 Home Assistant 選擇
- 升級與失敗回復涵蓋新增管理工具及模板
- 完整移除會清理本專案建立的診斷報告與手動設定備份

## 0.3.0

- 新增 `vps-sentinel` 中文維護中心，集中查看狀態與執行日常維護
- 新增 VPS Sentinel 安全升級工具，包含下載驗證、備份與啟動失敗回復
- 可安全切換資源模式與調整告警門檻，失敗時自動回復原設定
- 可產生只使用 Home Assistant 內建卡片的 VPS Sentinel 儀表板
- 儀表板安裝前會備份並驗證 Home Assistant 設定，失敗時自動回復
- 維護中心整合 Home Assistant 安全更新與完整移除工具

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
