# 開發日誌：Tailscale Serve 與既有服務的 443 連接埠衝突

> 日期：2026-07-30  
> 適用情境：Home Assistant、Tailscale Serve 與其他網路服務部署在同一台 VPS

## 背景

VPS Sentinel 預設可透過 Tailscale Serve，將本機的 Home Assistant
`127.0.0.1:8123` 轉成只在 tailnet 內可使用的 HTTPS 網址。

同一台 VPS 若已有其他網路服務，它可能正在監聽標準 HTTPS 連接埠
`TCP 443`。當程式綁定 `0.0.0.0:443`、`[::]:443` 或 `*:443` 時，
它會監聽所有網路介面，包括 VPS 的 Tailscale 位址。

兩項服務因此可能發生以下衝突：

```text
既有網路服務
└── TCP *:443
    ├── VPS 一般網路介面
    └── Tailscale 網路介面

Tailscale Serve
└── 預期使用 Tailscale 位址的 TCP 443
```

## 觀察到的現象

- Home Assistant Companion App 突然無法連線。
- 使用 Tailscale IP 存取 `8123` 時出現 Connection refused。
- Tailscale Serve 顯示已啟動，但開啟 HTTPS 網址時收到錯誤頁面。
- TLS 憑證不是 Tailscale 網域的憑證，而是既有服務提供的憑證。
- 將既有服務暫時限制在 VPS 私有網卡後，Tailscale HTTPS 恢復，但原本
  的公開服務可能無法正常連線。

## 排查過程

### 1. 確認 Home Assistant 的監聽位址

```bash
sudo ss -lntp | grep 8123
```

Home Assistant 必須至少監聽 Tailscale IP，才能使用下列直連網址：

```text
http://<TAILSCALE_IP>:8123
```

本次設定保留 loopback 給 Tailscale Serve，同時允許 Tailscale IP 直連：

```yaml
http:
  server_host:
    - 127.0.0.1
    - <TAILSCALE_IP>
  ip_ban_enabled: true
  login_attempts_threshold: 5
```

修改後先驗證設定，再重新啟動 Home Assistant：

```bash
sudo docker exec homeassistant \
  python -m homeassistant --script check_config --config /config
sudo docker restart homeassistant
```

### 2. 確認 DNS 與憑證

```bash
getent ahostsv4 <DEVICE>.<TAILNET>.ts.net
```

網域應解析至該 VPS 的 Tailscale IP。接著檢查實際收到的憑證：

```bash
echo | openssl s_client \
  -connect <DEVICE>.<TAILNET>.ts.net:443 \
  -servername <DEVICE>.<TAILNET>.ts.net 2>/dev/null |
  openssl x509 -noout -subject -issuer -ext subjectAltName
```

本次 DNS 解析正確，但憑證屬於同機的既有服務。這表示流量已抵達正確
的 VPS，卻被另一個監聽 `443` 的程式接走，並非 Tailscale DNS 故障。

### 3. 找出 443 的實際占用者

```bash
sudo ss -lntp | grep ':443'
```

常見的問題狀態如下：

```text
TCP *:443    <EXISTING_SERVICE>
```

`*:443` 代表該程式不只監聽 VPS 的主要網路介面，也會接收送往
Tailscale IP 的連線。任何使用相同 TCP 連接埠的程式都可能產生衝突，
判斷時應以實際監聽結果為準。

## 最終解法

若既有服務必須保留標準 `TCP 443`，最保守的做法是不修改該服務，
直接將 Tailscale Serve 改至 `TCP 8443`：

```bash
sudo tailscale serve reset
sudo tailscale serve --bg --https=8443 http://127.0.0.1:8123
```

最終的 Home Assistant HTTPS 網址格式為：

```text
https://<DEVICE>.<TAILNET>.ts.net:8443
```

檢查結果：

```bash
sudo tailscale serve status
sudo ss -lntup | grep -E ':443|:8443'
```

預期架構：

```text
既有網路服務       TCP 443
Tailscale Serve    TCP 8443  →  127.0.0.1:8123
Home Assistant     TCP 8123
```

同一個連接埠號的 TCP 與 UDP 是分開管理的。因此，其他程式已使用
`UDP 8443` 時，仍可由 Tailscale Serve 使用 `TCP 8443`，兩者不會衝突。

## 驗證清單

1. 原本使用 `TCP 443` 的服務可正常連線。
2. iPhone 已連上 Tailscale。
3. Safari 可開啟 `https://<DEVICE>.<TAILNET>.ts.net:8443`。
4. Home Assistant Companion App 可讀取儀表板。
5. `vps-monitor.service` 顯示 `active (running)`。
6. VPS Sentinel 日誌顯示 MQTT 已連線。

```bash
sudo systemctl status vps-monitor --no-pager
sudo journalctl -u vps-monitor -n 30 --no-pager
```

## 經驗與後續改善

- 看到錯誤憑證時，不能直接判定為 DNS 問題；應同時比對解析結果與
  `443` 的監聽程式。
- 在共用 VPS 上，安裝器不應假設 `TCP 443` 一定可用。
- 後續安裝流程應在啟用 Tailscale Serve 前檢查連接埠，若偵測到
  任何服務占用 `TCP 443`，應提示使用者保留既有服務，並提供 `8443`
  等替代選項。
- 不應為了解決 Tailscale Serve 衝突而直接改動既有服務的監聽位址；
  對正在使用的網路服務而言，這可能造成即時中斷。

## 安全提醒

- Tailscale Serve 僅提供給 tailnet 內的裝置，不等同公開至網際網路。
- `1883`、`8123` 等服務不應直接開放至公網。
- 文件、Issue 與診斷報告中應使用代稱，不要公開 Tailscale 網域、
  服務憑證、存取權杖、MQTT 密碼或 VPS 實際 IP。
