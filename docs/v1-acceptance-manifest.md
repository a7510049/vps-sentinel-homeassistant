# 1.0 實機驗收 manifest 標準

本標準固定 #65 人工實機驗收的欄位、coverage 與證據格式。Manifest 是私有驗收套件的一部分，不應直接公開未遮蔽的 Home Assistant 畫面、IP、Token、MQTT 密碼或環境檔。

## 固定表內欄位

每個 Gate 只使用下列欄位：

| 欄位 | 標準 |
| --- | --- |
| `id` | 工具產生的固定 ID，不自行改名 |
| `result` | 只接受 `PASS`；未完成保持 `PENDING` |
| `started_at`／`ended_at` | 含時區的 ISO-8601，建議 UTC |
| `command` | 實際執行指令或明確人工操作步驟 |
| `coverage` | 每個 Gate 預先定義的必驗情境，不可刪減 |
| `evidence` | 至少一個本機檔案，包含 label、kind、相對 path、SHA-256 |
| `notes` | 偏差、環境補充或後續 Issue／PR |

標題、欄位名稱與 Gate ID 不因版本或執行者自由改寫，避免再次出現同一件事有多套名稱。

## 建立範本

```bash
python3 scripts/v1-attestation.py init \
  --version "1.0.0-rc.1" \
  --build-ref "<commit SHA 或 Beta tag>" \
  --operator "qa-operator" \
  --output evidence/v1-attestation.json
```

工具會建立 24 個 PENDING Gate。不要刪除不適用項目；若某項無法完成，維持 PENDING 並建立修正 Issue，不能以文字說明取代 PASS。

## 證據檔

支援 `csv`、`json`、`log`、`screenshot`、`text`、`video`。所有 path：

- 必須相對於 manifest 所在目錄。
- 不得使用絕對路徑或 `../` 離開證據套件。
- 不得為空檔。
- 必須填寫檔案實際 SHA-256。
- 上傳或分享前必須遮蔽 IP、Token、密碼、原始 node ID 及其他個資。

同一張籠統截圖不能取代 coverage。例如 `ui_responsive_accessibility` 必須保留 mobile、desktop、dark、light、keyboard、reduced_motion；`credential_rotation` 必須同時證明 old_rejected 與 new_accepted。

## 封存與驗證

編輯完成後先重新 seal，否則 manifest checksum 會失敗：

```bash
python3 scripts/v1-attestation.py seal evidence/v1-attestation.json

python3 scripts/v1-attestation.py verify evidence/v1-attestation.json \
  --expected-version "1.0.0-rc.1" \
  --expected-ref "<commit SHA 或 Beta tag>" \
  --output evidence/v1-manual-gate.json
```

驗證器會重新計算 manifest 與每個證據檔的 SHA-256、檢查時間順序、固定 Gate 集合與 coverage。只有全部通過才輸出 `MANUAL_ACCEPTANCE_PASS`；再與自動化證據合併後，最終報告才可能是 `RELEASE_EVIDENCE_PASS`。
