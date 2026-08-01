# VPS Sentinel 1.0 Beta Gate

1.0 Beta 必須同時通過自動化與實機驗證，不能只因功能已合併就發布。

## 每次 PR 自動驗證

- Python 與 Go 契約、單元測試、語法與靜態檢查。
- Go Agent 原型 amd64／arm64 靜態建置與 checksum。
- 真實 Mosquitto 上的三個 node credential、ACL 隔離、Controller fleet snapshot 與 Home Assistant Discovery。
- combined 本機 credential 遷移、重跑及補償回復。
- enrollment bundle 建立、輪替、撤銷、過期與失敗回復。
- 前端卡片語法、鍵盤、深淺色資料模型與安裝註冊。

## Beta 前實機矩陣

| 場景 | 最低要求 |
| --- | --- |
| 節點來源 | 三個不同供應商或網路來源 |
| 架構 | 至少一台 amd64 與一台 arm64 |
| 連續運作 | Python 預設 Agent 連續 7 天 |
| 斷線 | Agent 斷網、Broker 重啟、Controller 重啟後自動恢復 |
| 身分 | credential 輪替後舊密碼失效；撤銷節點無法再發布 |
| 升級 | 0.9.8 → 1.0 Beta 保留 node_id 與 Home Assistant 實體 |
| 回復 | Agent、Controller、combined 各完成一次失敗回復 |
| UI | 手機／桌面、深色／淺色、鍵盤與 reduced motion |
| Go 評估 | Python／Go 各三次 24 小時原始 CSV；未達 ADR 門檻仍用 Python |

結果需記錄主機規格、OS、架構、版本、開始／結束時間、原始日誌與任何偏差。任一資料串台、舊 credential 仍可用、回復失敗或 7 天內非預期停止都是 Beta 阻擋項目。
