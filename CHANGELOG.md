# 更新紀錄

## 0.5.0

- 維護中心重新整理為系統總覽、監控設定、Home Assistant 與系統維護
  四個清楚的工作區
- 主畫面直接顯示版本、監控服務與 MQTT 即時狀態
- 統一選單編號、返回行為、狀態圖示與操作完成提示
- 健康檢查、備份、自動化與移除工具改用一致的繁體中文介面
- 移除工具預設動作改為安全取消，避免誤按 Enter 開始移除
- 更新工具在執行前清楚說明備份、驗證與失敗回復機制
- 更新成功後只保留最近一份專案回復備份，並移除 Home Assistant
  專用的舊映像 rollback 標籤
- 清理範圍限定於 VPS Sentinel 建立的內容，不執行全域 Docker 清理
- 事後清理失敗只顯示提醒，不會把已成功的更新誤判為失敗
- 新增 `status`、`settings`、`dashboard`、`doctor`、`backup`、
  `upgrade` 與 `ha-update` 子指令
- 支援 `NO_COLOR` 與非互動式狀態查詢，方便 SSH 紀錄及自動化使用
- 危險的完整移除操作移至系統維護區，執行前增加用途說明

## 0.4.1

- 修正升級後 MQTT 舊保留資料尚未包含 `last_report` 時的模板警告
- 所有 Discovery 模板在欄位暫時缺少時會安全顯示為未知
- 避免 Home Assistant 重新啟動期間的舊狀態讓新感測器變成不可用

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
