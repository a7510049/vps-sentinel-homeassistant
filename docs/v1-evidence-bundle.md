# 1.0 實機證據套件

本流程將 #65 中可機器判讀的證據整理成單一 PASS／FAIL 報告。它不會替代手機／桌面 UI、斷網與 Broker 重啟、credential 輪替／撤銷、升級回復及七天穩定性等人工實機 Gate。

## 固定受測版本

所有主機與六輪 benchmark 必須使用同一組：

```bash
VERSION="1.0.0-rc.1"
BUILD_REF="<40 字元 commit SHA 或 Beta tag>"
```

實機測試 main commit 時使用 commit SHA；已有 Beta tag 時可使用完整 tag。報告中的版本與 build ref 不一致會直接失敗。

## 收集主機報告

三個不同 VPS 供應商各執行一次，供應商與區域不可留白：

```bash
sudo vps-sentinel evidence \
  --expect-role agent \
  --provider "Cloud A" \
  --region "Taipei" \
  --build-ref "${BUILD_REF}" \
  --output "/root/vps-sentinel-evidence/agent-a.json"
```

Controller 或 combined 主機也要收集一份。每份 JSON 必須與旁邊的 `.json.sha256` 一起保留。驗證器要求：

- 至少三個不同 provider／region 的 Agent-capable 主機。
- Agent 主機同時涵蓋 amd64 與 arm64。
- 至少一個 Controller-capable 主機。
- 所有 live checks 為 PASS。
- 主機 fingerprint 不重複。
- 版本與 build ref 完全一致。
- JSON 的 SHA-256 未遭修改。

## 收集三台 Agent 七天穩定性

在每台 Agent 啟動一次 soak。程序會每分鐘記錄 boot fingerprint、systemd 狀態、MainPID 與 NRestarts；任一值顯示主機或服務重啟便立即失敗。

```bash
sudo python3 scripts/stability-soak.py \
  --version "${VERSION}" \
  --build-ref "${BUILD_REF}" \
  --interval 60 \
  --output /root/vps-sentinel-evidence/python-seven-day.csv
```

必須完整執行至少 604800 秒，間隔不得超過 300 秒。保留 CSV、`.summary.json` 與 summary 的 `.sha256`。短時間測試即使正常結束，也只會標示 INCOMPLETE，不能冒充七天證據。

## 收集 Python／Go 長時量測

依 [Go Agent 評估 ADR](adr/0002-go-agent-evaluation.md) 執行 Python 與 Go 各三輪。每輪都必須加入：

```bash
--version "${VERSION}" --build-ref "${BUILD_REF}"
```

摘要使用相對 artifact 路徑，因此複製時要把 summary JSON、CSV 與 log 放在同一證據目錄。比較器會重新計算 CSV／log SHA-256，不接受只有摘要或被修改的原始檔。

## 產生自動化 Gate 報告

```bash
python3 scripts/verify-v1-evidence.py \
  --evidence evidence/agent-a.json evidence/agent-b.json \
    evidence/agent-c.json evidence/controller.json \
  --soak evidence/agent-{a,b,c}.soak.summary.json \
  --python benchmarks/python-run-{1,2,3}.csv.summary.json \
  --go benchmarks/go-run-{1,2,3}.csv.summary.json \
  --expected-version "${VERSION}" \
  --expected-ref "${BUILD_REF}" \
  --output evidence/v1-automated-gate.json
```

成功時會建立權限 `0600` 的 JSON 與 `.sha256`。結果 `AUTOMATED_EVIDENCE_PASS` 只表示三台七天 soak、主機清冊與 benchmark 自動化證據完整；報告仍會保留 `remaining_manual_gates`，在 #65 全部完成並關閉以前仍不得發布 1.0。
