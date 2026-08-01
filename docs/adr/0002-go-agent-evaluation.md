# ADR 0002：以量測決定是否採用 Go Agent

- 狀態：實驗中
- 日期：2026-08-01
- 決策範圍：VPS Sentinel 1.0 Agent

## 問題

目前 Agent 使用 Python 與 psutil。Go 可能以單一執行檔降低 Python、venv 與依賴套件造成的安裝碎片，也可能減少常駐記憶體並改善跨架構發布；但現有採樣頻率不高，CPU 不一定是瓶頸，全面改寫還會帶來功能回歸與遷移成本。

因此，語言選擇必須與 1.0 架構拆分，不能用主觀印象決定。

## 決策

目前不承諾全面改寫。先凍結跨語言資料契約，再建立最小 Go Agent 原型，與現有 Python Agent 在相同環境中比較。

原型範圍只包含：

- CPU、記憶體、磁碟、負載、網路等核心收集。
- 節點 metadata 與 capabilities。
- MQTT TLS 連線、發布、離線狀態與自動重連。
- 結構化日誌、設定載入與優雅停止。

第一輪不包含遠端維護、Docker／systemd 的完整功能、舊版 Discovery 或安裝器重寫。

## 測試方法

### 固定環境

- 同一台低規格 VPS 或同規格隔離實例。
- 相同 Linux、Broker、TLS、採樣間隔及 payload。
- Python 與 Go 不同時執行，以免互相干擾。
- 各自暖機 30 分鐘，持續量測至少 24 小時。
- 每次測試至少重複三次並保留原始結果與腳本。

### 指標

| 指標 | 量測方式 |
| --- | --- |
| 常駐記憶體 | 暖機後、24 小時平均與 p95 RSS |
| CPU | 平均、p95 與尖峰 |
| 啟動時間 | 程序開始至第一次有效發布 |
| 發布延遲 | 採樣時間至 Broker 接收 |
| 可靠性 | 斷網、Broker 重啟、憑證錯誤及恢復 |
| 安裝負擔 | 下載大小、磁碟占用、依賴數與安裝步驟 |
| 功能相容 | 同一契約測試與 Home Assistant 結果 |
| 維護性 | 測試覆蓋、平台建置、漏洞更新與除錯能力 |

## 採用門檻

只有同時符合下列條件，才建議將 Go 設為 1.0 的預設 Agent：

1. 契約與核心功能測試完全相容。
2. amd64 與 arm64 均能產生可驗證的正式產物。
3. 相較 Python，p95 RSS 至少降低 30%，或單一執行檔使安裝／升級／回復明顯簡化且有測試證明。
4. CPU、發布延遲、斷線恢復與資料正確性沒有顯著退步。
5. 0.9.x 升級可保留設定、節點識別與 Home Assistant 實體。
6. 能一鍵回復 Python Agent。
7. 發布流程包含 checksum、SBOM 及依賴漏洞掃描。
8. 維護者確認 Go 工具鏈與測試成本可長期承擔。

「更多功能」本身不是換語言的理由；功能必須透過穩定契約與清楚邊界實現。

## 可重現實驗工具

repository 內的 `go-agent/` 是受限原型，不是正式安裝預設。CI 會在 Linux amd64 執行 Go 測試、`go vet`、靜態建置 amd64／arm64，並把 `--once` 輸出交由現有 Python `validate_envelope` 驗證，避免兩套語言各自解釋契約。

長時間比較前先停止正式 Agent，避免兩個程序使用相同 node credential：

```bash
sudo systemctl stop vps-monitor
sudo install -d -m 0700 /root/vps-sentinel-benchmarks
```

每次指令會先暖機 30 分鐘，再串流寫入 24 小時 CSV；提前退出、採樣失敗或量測不足不會被標成完成：

```bash
sudo python3 benchmarks/agent_benchmark.py \
  --name python \
  --command "/opt/vps-monitor/venv/bin/python /opt/vps-monitor/vps_monitor.py" \
  --env-file /etc/vps-monitor.env \
  --warmup 1800 --duration 86400 \
  --output /root/vps-sentinel-benchmarks/python-run-1.csv

sudo python3 benchmarks/agent_benchmark.py \
  --name go \
  --command "./go-agent" \
  --env-file /etc/vps-monitor.env \
  --warmup 1800 --duration 86400 \
  --output /root/vps-sentinel-benchmarks/go-run-1.csv
```

Python 與 Go 各完成三輪後，產生資源 Gate 報告：

```bash
sudo python3 benchmarks/compare_agent_benchmarks.py \
  --python /root/vps-sentinel-benchmarks/python-run-{1,2,3}.csv.summary.json \
  --go /root/vps-sentinel-benchmarks/go-run-{1,2,3}.csv.summary.json \
  --output /root/vps-sentinel-benchmarks/comparison.json
```

比較器會拒絕少於三輪、未完成 24 小時、不同主機或不同架構的資料。它只能判斷 RSS 資源門檻，最終決策仍須通過本 ADR 的契約、雙架構、可靠性、升級回復、SBOM／漏洞掃描與維護性條件。完成後使用 `sudo systemctl start vps-monitor` 恢復正式 Agent。

每個 Agent 分開執行、相同環境變數與 Broker，依本 ADR 重複三次。原始 CSV 不可只保留摘要；未完成 24 小時實機樣本與故障注入前，不得把 Go 設為預設。

## 決策結果

完成基準後只能選擇以下之一，並更新本 ADR：

- **採用 Go**：Go 成為預設 Agent，Python 進入有期限的相容期。
- **混合過渡**：Go 提供核心 Agent，尚未移植的能力由明確介面處理。
- **保留 Python**：持續改善封裝與單入口安裝，Go 原型停止或僅作研究用途。

若數據差異小，預設選擇保留 Python，以避免沒有使用者價值的重寫。

## 預期判斷

Go 最可能帶來的價值是單一執行檔、較少執行期依賴與較低記憶體，而不是大幅提高低頻監控的 CPU 效能。這是待驗證的推論，不是採用結論。

不論最後語言為何，Controller、UI 與安裝角色都依 ADR 0001 的契約運作，因此語言決策不會阻塞多 VPS 功能。
