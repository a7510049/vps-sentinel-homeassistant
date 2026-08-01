# 1.0 Fleet Card

狀態：Preview；Controller 安裝與資源自動註冊完成前不取代 0.9.x Apple Card。

Fleet Card 使用單一 `sensor.vps_sentinel_fleet_nodes` 的 attributes 顯示所有已註冊節點，不需要為每台 VPS 產生一份 YAML 或硬編碼 entity ID。

## 介面原則

- 異常排序固定為：嚴重、離線、資料過期、注意、正常。
- 總覽只顯示名稱、來源、狀態、最後回報及 CPU／記憶體／磁碟／負載。
- 點選節點後才展開 Agent、系統、更新、Docker 與異常服務。
- 支援名稱、供應商、區域及 labels 搜尋。
- 支援全部、需注意及離線篩選。
- 顏色以外同時提供圖示與文字狀態。
- 行動版不水平捲動，主要控制項至少 44 px。
- 尊重 Home Assistant 深淺色變數及系統 reduced motion 設定。
- 所有動態文字在插入 HTML 前轉義。

## Preview 設定

將 `home-assistant/www/vps-sentinel-fleet-card.js` 註冊為 JavaScript module 後，可加入：

```yaml
type: custom:vps-sentinel-fleet-card
entity: sensor.vps_sentinel_fleet_nodes
title: VPS Fleet
```

正式安裝器會自動部署並註冊資源；Preview 階段不要求穩定使用者手動操作。

## 狀態處理

- Controller 未建立實體：顯示缺少 Fleet 實體與檢查提示。
- 尚未註冊節點：顯示加入節點提示。
- 搜尋／篩選無結果：保留控制項並顯示無結果。
- stale：保留最後數值，但清楚標記「資料過期」。
- offline：離線優先於最後 health 狀態。
