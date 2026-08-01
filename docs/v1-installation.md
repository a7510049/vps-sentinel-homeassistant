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
5. Broker transaction 先套用 Controller 與本機 Agent 的過渡期 password、ACL、config。
6. combined 角色原子更新本機 Agent 環境檔，切換為專用 `vps-node-{id}` credential，並啟用 v1 contract。
7. 驗證 Mosquitto、Controller 與本機 Agent 後，以第二次 Broker transaction 撤銷共用 `vps-monitor` credential。
8. 任一切換步驟失敗時，Enrollment Store、Agent 環境檔及 Broker policy 一起補償回復。
9. Fleet Card 以暫存檔與 `os.replace` 部署。
10. 單一入口輸出唯一完成摘要與仍需人工處理的 Home Assistant 步驟。

Controller 密碼只保存於 root-only 的環境檔，不顯示在完成摘要或日誌。

## 重跑

- setup 沿用既有 Home Assistant、MQTT password 與 Agent 設定。
- Controller 元件安裝器沿用既有環境檔，不覆寫密碼。
- Broker transaction 從目前 password file 建立 staging 副本，再更新 Controller 帳號。
- combined 本機 Agent 若已使用正確 node credential，重跑不會輪替密碼；已不存在的 legacy 帳號也可安全再次撤銷。
- requirements hash 未變時不重建 venv。
- Fleet Card 使用原子取代。

## Agent enrollment bundle

在 Controller 建立一次性 bundle：

```bash
sudo vps-sentinel-enroll create tokyo-web-01 \
  --name "東京網站" \
  --broker-host controller.example.ts.net
```

預設有效 15 分鐘，檔案權限固定為 `0600`。輸出只顯示 bundle 路徑與期限，不顯示 MQTT 密碼。透過安全通道將檔案傳到 Agent 後執行：

```bash
sudo bash install.sh --config /path/to/tokyo-web-01.json
```

`--config` 會自動使用 agent 角色、驗證欄位與期限、寫入 `0600` 環境檔、開啟 v1 contract publishing、執行既有服務驗證；成功後刪除一次性 bundle。安裝失敗則還原原本環境與 CA，保留 bundle 供期限內重試。

輪替與撤銷：

```bash
sudo vps-sentinel-enroll rotate tokyo-web-01 \
  --broker-host controller.example.ts.net
sudo vps-sentinel-enroll revoke tokyo-web-01
```

Enrollment Store、password file 與 ACL 由同一流程更新。Broker 交易失敗時 Store 與 bundle 都會回復或移除，Controller 重新載入原本名冊。

## 備份、復原與移除

`sudo vps-sentinel backup` 的 format 3 備份會一起保存 Home Assistant 設定、本機 Agent、Controller 環境、Enrollment Store、Mosquitto password／ACL／config 與 Fleet Card。復原前會先建立目前狀態的安全備份；Controller、Agent、Broker 或 Home Assistant 任一驗證失敗時，自動回復復原前狀態。

完整移除會一併停止並移除 Controller、Enrollment Store、Fleet Card、專用 MQTT 帳號與 ACL；若 Broker 密碼檔仍有其他服務帳號，會保留 Broker 設定，避免影響共用服務。只移除本機 Agent 時不會碰 Controller 與名冊。

## 尚待完成

- 非互動 combined／controller JSON 設定與完整 preflight report。
- Fleet Card Home Assistant resource 自動註冊。
- Controller／Agent／combined 的安全升級與實機復原驗證。
