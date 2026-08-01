# 1.0 Mosquitto 權限與交易

狀態：交易核心完成；尚未由單一角色安裝器呼叫。

## 既有問題

0.9.x 設定只有 `password_file` 與 `allow_anonymous false`。這能阻止匿名連線，但所有成功登入的帳號仍可存取其他節點主題，不足以作為多來源 VPS 的身分邊界。

## 固定 ACL

- **Home Assistant**：保留 `readwrite #`，確保既有 MQTT 整合與其他裝置不受 VPS Sentinel 限制。
- **Controller**：只能讀取 v1 node streams，並寫入 Controller fleet namespace 與 Home Assistant Discovery。
- **0.9.x Agent**：只能寫入綁定 `VPS_ID` 的 legacy 主題、讀取自己的 command，並寫 Discovery。
- **1.0 Agent**：只能寫入自己的 metadata、resources、health、availability、events，並讀取自己的 commands。

每個 v1 node 使用明確主題，不提供跨節點 wildcard write。

## 原子交易

Broker transaction 依序：

1. 取得跨程序檔案鎖。
2. 在鎖內讀取 password、ACL 與 Mosquitto config 的完整快照。
3. 在 staging 目錄複製既有 password file。
4. 只在 staging password file 新增或輪替帳號。
5. 產生完整 ACL 與 config。
6. 以同目錄暫存檔、`fsync`、`os.replace` 逐一套用。
7. 設定 password／ACL 為 `0640 root:mosquitto`，config 為 `0644`。
8. 重啟 Mosquitto。

若任何寫入、權限或重啟失敗，交易會還原三個檔案的內容、mode、uid、gid，再嘗試恢復舊 Mosquitto。錯誤訊息不包含密碼。

檔案系統無法提供跨三個路徑的單一步驟原子取代，因此「交易」的保證來自鎖、完整快照與失敗回復；正式安裝測試仍須注入每個階段的失敗。

## 密碼處理

新密碼只傳給 `mosquitto_passwd` 的 staging 檔案，不先修改正式 password file。工具失敗時，正式檔案不變，例外文字不包含密碼。後續安裝入口必須避免 Shell trace、日誌與完成摘要洩漏密碼。
