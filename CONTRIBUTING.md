# 貢獻指南

感謝協助改善 VPS Sentinel for Home Assistant。

## 回報問題

建立 Issue 前，請先確認問題可在 `main` 最新版本重現，並提供：

- 作業系統與版本
- 安裝方式及所選資源模式
- 相關服務狀態與已移除敏感資訊的日誌
- 預期行為與實際行為

請勿貼上 MQTT 密碼、Token、私鑰、公網 IP 或完整環境檔。安全問題請
依照 [安全政策](SECURITY.md) 私下回報。

## 1.0 開發規則

1.0 相關工作必須先閱讀 [1.0 開發標準](docs/v1-development-standard.md) 與 [1.0 路線圖](docs/v1-roadmap.md)。架構或語言選擇須透過 ADR；缺少完成條件、相容性、測試與回復方式的工作不得進入實作。

## 提交變更

1. 從 `main` 建立功能分支。
2. 保持安裝提示與文件淺顯、可操作。
3. 執行 Shell 與 Python 語法檢查。
4. 說明變更目的、測試方式及相容性影響。
5. 提交 Pull Request。

新功能應維持安全預設值，並避免增加低資源 VPS 的常駐負擔。

準備版本說明時，請遵循 [GitHub Release 內容標準](docs/release-standard.md)。
