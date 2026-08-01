# 1.0 節點資料契約

狀態：Phase 0 基準；尚未取代 0.9.x MQTT 主題。

本文件與 [JSON Schema](schema/node-message-v1.schema.json) 定義 Python、Go 與 Controller 之間的共同邊界。任何不相容變更都必須建立新版 schema，不得靜默修改 1.0。

## MQTT 主題

```text
vps-sentinel/v1/nodes/{node_id}/metadata
vps-sentinel/v1/nodes/{node_id}/resources
vps-sentinel/v1/nodes/{node_id}/health
vps-sentinel/v1/nodes/{node_id}/availability
vps-sentinel/v1/nodes/{node_id}/events
```

`node_id` 必須符合 `^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$`。它是不可變的技術識別；重新命名只修改 `display_name`。

| Stream | QoS | Retain | 用途 |
| --- | ---: | --- | --- |
| metadata | 1 | 是 | 版本、能力與顯示中繼資料 |
| resources | 0 | 是 | 高頻 CPU、記憶體與網路快照 |
| health | 1 | 是 | 磁碟、服務、更新與整體健康 |
| availability | 1 | 是 | Agent 在線狀態；必須設定離線遺囑 |
| events | 1 | 否 | 維護與告警事件，不得重播舊命令結果 |

Controller 收到訊息後自行增加 `received_at`；Agent 不得偽造此欄位。

## 共用 envelope

```json
{
  "schema_version": "1.0",
  "message_type": "resources",
  "node": {
    "id": "tokyo-web-01",
    "display_name": "東京網站",
    "agent_version": "1.0.0-alpha.1",
    "capabilities": ["resources.basic", "network.throughput"],
    "provider": "Example Cloud",
    "region": "jp-east",
    "labels": {
      "environment": "production",
      "role": "web"
    }
  },
  "observed_at": "2026-08-01T10:30:00Z",
  "sequence": 42,
  "data": {
    "cpu_percent": 12.3,
    "memory_percent": 48.1
  }
}
```

### 固定規則

- `schema_version` 固定為 `1.0`。
- `message_type` 必須與主題 stream 對應。
- `observed_at` 是含時區的 RFC 3339 採樣時間，輸出統一為 UTC。
- `sequence` 在 Agent 程序生命週期中單調遞增；Controller 以時間、序號與連線狀態判斷陳舊資料，不把它當全域永久序號。
- `capabilities` 採小寫、具命名空間的名稱；UI 只顯示節點宣告支援的功能。
- `provider`、`region` 與 `labels` 只供展示、篩選及分組，不參與身分判斷。
- envelope 與 `node` 不接受未知欄位；各 stream 的 `data` 會由後續子 schema 逐步固定。
- 密碼、Token、私鑰、Authorization 等秘密不得出現在任何 payload。

## Controller 驗證

Controller 接收時必須依序檢查：

1. MQTT 憑證是否有權發布指定 `node_id`。
2. 主題中的 `node_id` 是否與 `node.id` 相同。
3. schema、message type、時間、序號及 payload 是否有效。
4. 同一 `node_id` 是否由不同憑證或同時連線重複宣告。
5. Agent 版本與能力是否受支援。

驗證失敗的資料不得更新 Home Assistant 實體；Controller 應記錄不含秘密的診斷事件並提供修正指引。

## 離線與資料過期

- `availability` 表示 MQTT 連線／Agent 生命週期。
- `resources` 與 `health` 分別依預期更新頻率判斷是否過期。
- Agent 離線與資料過期是不同狀態。
- UI 顯示舊數值時必須同時標示過期，不得呈現為即時狀態。

## 0.9.x 相容

現有 `vps/{VPS_ID}`、`resources`、`status` 與 Discovery 主題在本階段維持不變。後續 adapter 將：

1. 驗證既有 `VPS_ID` 是否可作為 `node_id`。
2. 將現有 resource 與 status payload 映射成 v1 envelope。
3. 保留現有 Home Assistant unique ID 與 default entity ID。
4. 在切換前提供碰撞及 entity 遷移預覽。

只有 adapter、契約測試與復原流程完成後，Production Agent 才會開始發布 v1 主題。

## Phase 0 預覽開關

安裝器會部署契約與相容模組，但預設寫入 `PUBLISH_V1_CONTRACT="false"`，因此穩定使用者不會多出任何 v1 訊息。開發測試環境可手動改為 `true` 並重新啟動服務，讓 Agent 在保留 0.9.x 主題的同時雙軌發布 `resources`、`health` 與 `metadata`。

此開關目前不代表 1.0 已可用；availability、Controller 驗證、Discovery 接管與遷移預覽完成前不得在正式安裝預設啟用。
