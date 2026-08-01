# 1.0 節點註冊與 MQTT 權限

狀態：Controller 核心實作；Broker 套用與安裝器接線尚未完成。

## 信任模型

MQTT 訂閱訊息通常不會攜帶可供 Controller 驗證的發布者密碼，因此 Controller 不信任 payload 自稱的身分。1.0 使用兩層保護：

1. Enrollment Store 將穩定 `node_id` 對應到唯一 Broker username。
2. Mosquitto ACL 限制該 username 只能發布自己的節點主題。

Controller 收到資料時，再驗證 topic、envelope 與已註冊 `node_id` 是否一致。

## 註冊資料

持久化檔案只包含：

- `node_id`
- Broker username
- 顯示名稱
- 建立與最近輪替時間

新密碼以安全亂數產生，只在註冊或輪替的回傳值出現一次。Store 不保存密碼、Token 或私鑰，物件的除錯輸出也會隱藏密碼。檔案採原子取代並設為 `0600`。

## 最小權限 ACL

每個 Agent 帳號只能：

- 寫入自己的 metadata、resources、health、availability、events。
- 讀取自己的 commands。

它不能讀取其他節點、寫入其他 `node_id`、建立 Home Assistant Discovery 或寫入 Controller fleet 狀態。

Controller 帳號只能：

- 讀取所有已註冊 v1 node streams。
- 寫入 Controller namespace。
- 寫入 Home Assistant Discovery。

Broker 的匿名存取維持關閉。

## 生命週期

- **Register**：拒絕既有 ID，產生一次性密碼並寫入公開註冊 metadata。
- **Rotate**：username 與 node ID 不變，只產生新密碼並記錄輪替時間。
- **Revoke**：移除 registry binding；Broker 密碼與 ACL 必須在同一安裝器交易中移除。
- **Re-enroll**：撤銷完成後才允許重新使用相同 node ID，並需要明確的 Home Assistant 遷移／接管確認。

## 尚未接線的安全要求

安裝器整合時必須：

1. 在暫存檔完成 passwd 與 ACL 更新。
2. 執行 `mosquitto -c ... -t` 或等效設定驗證。
3. 驗證成功後才原子取代正式檔案並 reload。
4. 任一步驟失敗時同時回復 passwd、ACL 與 Enrollment Store。
5. 不得用會讓密碼長時間出現在程序清單、Shell history 或日誌的方式呼叫工具。
6. 最終只向使用者顯示一次節點安裝資料，並提醒安全保存。
