# 1.0 Controller 節點 Registry

狀態：Phase 0 核心實作；尚未接上正式 MQTT Broker 或 Home Assistant Discovery。

Registry 是多來源 VPS 的信任邊界。它不因 MQTT 成功送達就直接更新介面，而是先驗證資料契約、主題身分、憑證綁定、時間與序號。

## 接收順序

1. 拒絕超過 64 KiB、非 UTF-8 或非 JSON 的 payload。
2. 依 v1 契約驗證所有 envelope 與 node 欄位。
3. 確認 MQTT topic 中的 `node_id`、stream 與 envelope 完全一致。
4. 將 `node_id` 綁定到 Controller 取得的憑證識別。
5. 拒絕另一憑證同時宣告相同 `node_id`。
6. 依每個 stream 的採樣時間與 sequence 阻止舊資料覆蓋新資料。
7. 通過後才更新公開 snapshot。

`credential_id` 代表 Controller 從 MQTT 驗證結果取得的不可逆識別或指紋，不是密碼或 Token；它不得出現在 Home Assistant 狀態、API 或診斷輸出。

## 節點狀態

Registry 將狀態分為：

- `normal`、`warning`、`critical`：來自有效 health stream。
- `stale`：Agent 最近仍有活動，但 resources 或 health 超過各自 TTL。
- `offline`：收到明確離線狀態，或所有資料超過離線門檻。

預設 TTL：

| Stream | TTL |
| --- | ---: |
| resources | 60 秒 |
| health | 600 秒 |
| metadata | 86400 秒 |
| 推定離線 | 90 秒無任何訊息 |

正式 Controller 會讓 TTL 依 Agent 回報間隔計算並設合理上下限；目前數值只作測試基準。

## Agent 重啟與重播

sequence 在同一 Agent 程序內單調增加。若 sequence 變小但 `observed_at` 明確更新，Registry 視為 Agent 重啟並接受；若 sequence 與時間都不新，則視為延遲或重播並拒絕。

後續 availability 實作會加入 session 身分，進一步避免時鐘錯誤造成歧義。

## 目前完成

- 多節點隔離與穩定排序。
- topic／payload 身分一致性。
- 單一節點憑證綁定與碰撞拒絕。
- 每個 stream 的舊訊息防護。
- 在線、離線與資料過期的分離。
- 公開 snapshot 不包含憑證資訊。

## 接入正式 Controller 前仍需

- MQTT TLS 連線與 ACL／憑證指紋來源。
- session-aware availability 與 Last Will。
- 持久化 registry、憑證輪替及節點移除。
- Home Assistant Discovery 與 fleet API。
- 故障注入、Controller 重啟與備份／復原測試。

## MQTT Runtime

Controller runtime 訂閱 `vps-sentinel/v1/nodes/+/+`。每則訊息會先由 topic 解析 `node_id`，再向 Enrollment Store 查詢既有 username binding；未註冊節點不會進入 Registry。

通過驗證後，Controller 以 QoS 1 retained 發布：

```text
vps-sentinel/v1/controller/fleet
```

fleet snapshot 包含產生時間、節點數、在線數、問題數與排序後的公開節點狀態，不包含 username、credential ID、密碼或 Token。Runtime 會定期重新建立 snapshot；即使沒有新 MQTT 訊息，TTL 到期仍會把節點改為 stale 或 offline。若公開狀態沒有變更，則不重複發布。

正式接入 systemd 前仍需完成 Controller availability、設定檔、Broker ACL 交易、日誌速率限制及安裝／回復測試。
