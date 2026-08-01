# 1.0 單一安裝入口

狀態：Preview；互動式角色流程已接線，非互動 JSON 設定與節點註冊命令仍在後續階段。

所有使用者從 repository 根目錄執行：

```bash
sudo bash install.sh
```

不需要直接尋找 `setup.sh`、`controller/install-component.sh` 或 `vps-monitor/install.sh`。這些檔案是可獨立測試的內部元件邊界。

## 角色

| 角色 | 內容 |
| --- | --- |
| `combined` | Home Assistant、Mosquitto、Controller、本機 Agent、Fleet Card |
| `controller` | Home Assistant、Mosquitto、Controller、Fleet Card；不安裝本機 Agent |
| `agent` | 只安裝 Agent，連線到既有 Controller |

可直接指定角色：

```bash
sudo bash install.sh --role combined
sudo bash install.sh --role controller
sudo bash install.sh --role agent
```

## Dry-run

Dry-run 在 root 權限檢查與任何變更前結束：

```bash
bash install.sh --role controller --dry-run
```

它會顯示角色、順序及預期元件，不安裝套件、不建立檔案、不啟動服務。

## Controller／combined 交易順序

1. 既有 setup 完成系統、Home Assistant、Mosquitto 與選定的本機 Agent。
2. Controller 元件以停止狀態安裝。
3. 建立或沿用 Controller 專用 MQTT 密碼。
4. 從 Enrollment Store 與 legacy VPS_ID 產生完整 ACL。
5. Broker transaction 套用 password、ACL、config。
6. 同一個 restart callback 驗證 Mosquitto 與 Controller。
7. 失敗時 Broker 三個檔案回復。
8. Fleet Card 以暫存檔與 `os.replace` 部署。
9. 單一入口輸出唯一完成摘要與仍需人工處理的 Home Assistant 步驟。

Controller 密碼只保存於 root-only 的環境檔，不顯示在完成摘要或日誌。

## 重跑

- setup 沿用既有 Home Assistant、MQTT password 與 Agent 設定。
- Controller 元件安裝器沿用既有環境檔，不覆寫密碼。
- Broker transaction 從目前 password file 建立 staging 副本，再更新 Controller 帳號。
- requirements hash 未變時不重建 venv。
- Fleet Card 使用原子取代。

## 尚待完成

- `--config` 非互動 JSON 設定與完整 preflight report。
- 一條 Agent enrollment 命令與短效憑證。
- combined 本機 Agent 從 legacy 帳號自動遷移到專用 node credential。
- Fleet Card Home Assistant resource 自動註冊。
- Controller／Agent／combined 的升級、備份、復原與移除端到端測試。
