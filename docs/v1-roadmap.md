# VPS Sentinel 1.0 路線圖

本路線圖把 1.0 拆成可獨立驗收的階段。實作順序固定為「契約 → 多節點 → 介面 → 安裝整合 → 語言決策 → 穩定化」，避免同時重寫所有元件。

## 核心使用情境

使用者可在一個 Home Assistant 中加入位於不同供應商或網路的 VPS，快速看出哪台需要處理，並能從同一套安裝工具新增、升級、診斷或移除節點。

## Phase 0：基準與契約

目標：凍結現況並先定義跨語言、跨版本的邊界。

- 建立 0.9.x 行為與效能基準。
- 定義 versioned node schema、能力模型與錯誤格式。
- 將顯示名稱與穩定 `node_id` 分離。
- 建立舊 MQTT 主題的相容層與遷移測試。
- 將現有 Python 程式分出 collector、transport、discovery 與 actions 邊界。
- 補齊斷線、重連、資料過期、重複 ID 與升級測試。

完成條件：在不改變使用者行為下，契約測試可驗證 Python Agent 的輸出。

## Phase 1：多 VPS 主控能力

目標：一個 Controller 能可靠管理多個來源的節點。

- 建立節點註冊、清單、能力與最後回報狀態。
- 支援不同 MQTT 網路入口或經安全網路連入同一 Broker 的部署方式。
- 偵測重複 ID、過期資料與不相容 schema。
- 由 Controller 統一產生 Home Assistant Discovery，避免命名碰撞。
- 保留 0.9.x entity ID 映射，提供遷移預覽。
- 節點個別故障不得阻塞整體更新。

完成條件：至少三台不同來源的 VPS 可同時加入、重新命名、離線與恢復，且資料不串台。

## Phase 2：統一監控介面

目標：介面先回答「哪一台有問題」，再提供細節。

### 總覽

- 健康狀態、名稱、來源／區域。
- CPU、記憶體、磁碟、告警數與最後回報。
- 搜尋、狀態篩選、標籤分組與排序。
- 離線、資料過期、部分失敗與版本不相容提示。

### 節點詳情

- 資源趨勢、網路、服務、容器及安全資訊。
- 可用能力決定顯示內容，不呈現無效控制項。
- 高風險維護操作需要清楚確認、執行狀態與結果。

完成條件：手機及桌面均無水平捲動，異常可在總覽直接辨識，並通過深色／淺色、鍵盤操作及減少動態效果檢查。

## Phase 3：一體化安裝體驗

目標：使用者不必在多份文件與腳本之間尋找下一步。

### 安裝角色

- `controller`：主控、Broker 整合、Home Assistant Discovery 與 UI。
- `agent`：只安裝監控 Agent，連到既有 Controller。
- `combined`：單機同時安裝 Controller 與 Agent，延續目前的快速體驗。

### 固定流程

`preflight → role → plan → apply → verify → summary`

- 一個入口、一份設定檔、一組一致指令。
- 提供 dry-run、非互動模式、階段化日誌與診斷包。
- 自動偵測現有元件，重跑不重複建立或覆寫秘密。
- 主控端產生一條節點註冊命令；完成後自動驗證端到端資料。
- 升級前先備份設定並顯示相容性；失敗可回到上一可用版本。
- 最終畫面只保留仍需人工完成的事項。

完成條件：全新 combined 安裝、既有 0.9.x 升級、增加遠端 Agent 與失敗復原均有自動化測試及實機演練。

## Phase 4：Go Agent 實驗與決策

目標：以相同資料契約比較 Go 原型與 Python Agent，不先承諾全面改寫。

- Go 原型只實作資源收集、能力宣告、MQTT 發布與重連。
- 使用相同節點、頻率、Broker 與 24 小時負載。
- 比較 RSS、CPU 平均／p95、啟動時間、發布延遲、重連可靠度與安裝大小。
- 驗證 amd64／arm64、靜態產物、checksum、SBOM、升級及回復。
- 依 [Go 評估 ADR](adr/0002-go-agent-evaluation.md) 決定採用、混合或保留 Python。

完成條件：基準資料可重現，功能相容與遷移方案均通過審查。

## Phase 5：穩定化與 1.0

- 三台以上異質節點連續運作至少 7 天。
- 完成故障注入、憑證輪替、升級與復原演練。
- 凍結 schema 與使用者可見文字。
- 完成安裝、遷移、疑難排解及安全文件。
- 發布 Beta、RC，解決阻擋問題後才發布 1.0。

## Issue 與里程碑標籤

建議所有 1.0 工作使用一致欄位：

| 欄位 | 選項 |
| --- | --- |
| Phase | `phase/0-contract` 至 `phase/5-stable` |
| Area | `area/agent`、`area/controller`、`area/ui`、`area/installer`、`area/docs` |
| Priority | `priority/p0`、`priority/p1`、`priority/p2` |
| Risk | `risk/security`、`risk/compatibility`、`risk/migration`、`risk/performance` |
| Status | `status/needs-spec`、`status/ready`、`status/blocked` |

## 明確的開發順序

1. 完成 Phase 0，不新增大型 UI 或語言重寫。
2. Phase 1 的多節點資料可靠後，才把 UI 從單機卡片改為 fleet view。
3. 契約與安裝角色穩定後，才開始 Go 比較原型。
4. Go 決策不得阻塞 Python 路徑的多節點與安裝改善。
5. 每個階段都要能單獨發布 Preview，並能回到上一版本。
