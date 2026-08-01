# ADR 0001：1.0 採 Agent／Controller 架構

- 狀態：提議
- 日期：2026-08-01
- 決策範圍：VPS Sentinel 1.0

## 背景

0.9.x 的 `vps_monitor.py` 同時負責資源收集、MQTT、Home Assistant Discovery、遠端操作與執行週期；安裝與儀表板也以單台 VPS 為主要情境。雖然現有 `VPS_ID` 與 `vps/{VPS_ID}` 主題已能區分節點，但缺少中央節點清單、版本化契約、碰撞處理及跨節點 UI。

若直接在目前單體程式加入更多條件，多 VPS、安裝角色、相容層及未來 Go Agent 會互相綁定。

## 決策

1. 1.0 將系統劃分為 Agent、Controller、Installer 與 UI 四個邊界。
2. Agent 發布版本化的節點資料及能力，不負責 fleet UI。
3. Controller 維護節點 registry，驗證 schema，處理過期／離線狀態，並統一產生 Home Assistant Discovery。
4. UI 只讀取 Controller 定義的穩定實體與 registry，不硬編碼單一 VPS。
5. Installer 依 `controller`、`agent`、`combined` 角色組合元件。
6. 0.9.x 主題在過渡期由 adapter 支援；不得一次切斷既有安裝。

## 身分模型

- `node_id`：不可變、唯一、適合作為實體識別；建立後不可因重新命名而改變。
- `display_name`：可修改的使用者名稱。
- `provider`、`region`、`labels`：可選中繼資料。
- `schema_version`、`agent_version`、`capabilities`：相容與功能協商。
- `observed_at`、`received_at`：分辨節點採樣時間與主控接收時間。

重複 `node_id`、過舊 schema 或時鐘異常時，Controller 必須隔離資料並提供可操作的錯誤訊息。

## 資料流

```text
Linux VPS                    Controller                    Home Assistant
┌────────────┐               ┌────────────────┐            ┌──────────────┐
│ Agent      │ -- MQTT/TLS ->│ Registry       │----------->│ Discovery    │
│ collectors │               │ validation     │            │ entities     │
│ actions*   │<-- commands --│ policy/audit   │<-----------│ dashboard    │
└────────────┘               └────────────────┘            └──────────────┘
* 遠端操作為選配且預設關閉
```

## 過渡方案

1. 先為現有 Python Agent 加入內部分層與契約測試，不改變 0.9.x 行為。
2. Controller 接受舊 `vps/{VPS_ID}`，映射到 registry。
3. 新 Agent 使用版本化契約；Controller 對 Home Assistant 維持穩定 entity ID。
4. 提供遷移預覽，確認沒有自動化引用損壞後才切換。
5. 舊契約至少保留一個穩定版本的公告期，再依棄用政策移除。

版本化主題的精確名稱與 payload schema 將由獨立規格 PR 決定；本 ADR 不提前鎖死命名。

## 結果

### 優點

- 多節點識別、狀態與 Discovery 由同一處管理。
- Agent 可用 Python 或 Go 實作，只要遵守相同契約。
- UI 與資料收集解耦，容易測試離線、過期及部分失敗。
- 安裝角色與權限邊界更清楚。

### 成本

- Controller 成為新元件，需要處理升級與可用性。
- 相容 adapter 增加過渡期複雜度。
- 集中 Discovery 前必須仔細保留既有 entity ID。

## 被否決的替代方案

- **每個 Agent 繼續直接管理所有 Discovery**：初期改動小，但節點碰撞、版本差異及 fleet UI 難以集中治理。
- **立即建立雲端服務**：超出自架與 Home Assistant 優先的 1.0 範圍。
- **先全面改寫 Go 再做多節點**：同時改變語言與架構，無法隔離回歸來源，也沒有基準證明必要性。
