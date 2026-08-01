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
  --python benchmarks/python-run-{1,2,3}.csv.summary.json \
  --go benchmarks/go-run-{1,2,3}.csv.summary.json \
  --expected-version "${VERSION}" \
  --expected-ref "${BUILD_REF}" \
  --output evidence/v1-automated-gate.json
```

成功時會建立權限 `0600` 的 JSON 與 `.sha256`。結果 `AUTOMATED_EVIDENCE_PASS` 只表示自動化證據完整；報告會保留 `remaining_manual_gates`，在 #65 全部完成並關閉以前仍不得發布 1.0。
