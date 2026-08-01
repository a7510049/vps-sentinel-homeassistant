const FLEET_CARD_VERSION = "1.0.0-alpha.1";

class VpsSentinelFleetCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { entity: "sensor.vps_sentinel_fleet_nodes" };
    this._hass = null;
    this._signature = "";
    this._query = "";
    this._filter = "all";
    this._expanded = new Set();
  }

  static getStubConfig() {
    return { entity: "sensor.vps_sentinel_fleet_nodes", title: "VPS Fleet" };
  }

  setConfig(config) {
    this._config = {
      entity: "sensor.vps_sentinel_fleet_nodes",
      title: "VPS Fleet",
      ...config,
    };
    if (!this._config.entity || typeof this._config.entity !== "string") {
      throw new Error("VPS Fleet Card 需要有效的 entity");
    }
    this._signature = "";
    this.render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.entity];
    const signature = state
      ? JSON.stringify([
          state.state,
          state.last_updated,
          state.attributes.generated_at,
          state.attributes.node_count,
          state.attributes.problem_count,
          state.attributes.nodes,
        ])
      : "missing";
    if (signature !== this._signature) {
      this._signature = signature;
      this.render();
    }
  }

  getCardSize() {
    return 5;
  }

  escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  statusInfo(status) {
    return {
      critical: { label: "嚴重", icon: "!", rank: 0 },
      offline: { label: "離線", icon: "×", rank: 1 },
      stale: { label: "資料過期", icon: "↻", rank: 2 },
      warning: { label: "注意", icon: "!", rank: 3 },
      normal: { label: "正常", icon: "✓", rank: 4 },
    }[status] || { label: "未知", icon: "?", rank: 5 };
  }

  number(value, digits = 1) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toFixed(digits)
      : "—";
  }

  relativeTime(value) {
    const timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp)) return "尚無回報";
    const seconds = Math.round((timestamp - Date.now()) / 1000);
    const formatter = new Intl.RelativeTimeFormat("zh-TW", { numeric: "auto" });
    if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
    const minutes = Math.round(seconds / 60);
    if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
    return formatter.format(Math.round(hours / 24), "day");
  }

  nodeSearchText(item) {
    const node = item.node || {};
    const labels = node.labels || {};
    return [
      node.id,
      node.display_name,
      node.provider,
      node.region,
      ...Object.keys(labels),
      ...Object.values(labels),
    ]
      .join(" ")
      .toLocaleLowerCase("zh-TW");
  }

  visibleNodes(nodes) {
    const query = this._query.trim().toLocaleLowerCase("zh-TW");
    return [...nodes]
      .filter((item) => {
        if (this._filter === "problems" && item.status === "normal") return false;
        if (this._filter === "offline" && item.status !== "offline") return false;
        return !query || this.nodeSearchText(item).includes(query);
      })
      .sort((left, right) => {
        const rank = this.statusInfo(left.status).rank - this.statusInfo(right.status).rank;
        if (rank !== 0) return rank;
        const leftName = left.node?.display_name || left.node?.id || "";
        const rightName = right.node?.display_name || right.node?.id || "";
        return leftName.localeCompare(rightName, "zh-TW");
      });
  }

  metric(label, value, suffix = "") {
    return `
      <div class="metric">
        <span class="metric-label">${this.escape(label)}</span>
        <strong>${this.escape(value)}${this.escape(suffix)}</strong>
      </div>
    `;
  }

  nodeCard(item) {
    const node = item.node || {};
    const resources = item.streams?.resources?.data || {};
    const health = item.streams?.health?.data || {};
    const status = this.statusInfo(item.status);
    const id = String(node.id || "");
    const expanded = this._expanded.has(id);
    const provider = node.provider || "未設定供應商";
    const region = node.region || node.labels?.country_code?.toUpperCase() || "";
    const failedServices =
      health.failed_services && health.failed_services !== "無"
        ? health.failed_services
        : "無";
    const stale = Array.isArray(item.stale_streams)
      ? item.stale_streams.join("、")
      : "";

    return `
      <article class="node status-${this.escape(item.status || "unknown")}">
        <button
          class="node-summary"
          type="button"
          data-node-id="${this.escape(id)}"
          aria-expanded="${expanded}"
          aria-label="${this.escape(node.display_name || id)}，${status.label}，開啟詳細資料"
        >
          <span class="status-symbol" aria-hidden="true">${status.icon}</span>
          <span class="identity">
            <strong>${this.escape(node.display_name || id)}</strong>
            <span>${this.escape(provider)}${region ? ` · ${this.escape(region)}` : ""}</span>
          </span>
          <span class="status-copy">
            <strong>${status.label}</strong>
            <small>${this.escape(this.relativeTime(item.last_received_at))}</small>
          </span>
          <span class="chevron" aria-hidden="true">${expanded ? "−" : "+"}</span>
        </button>

        <div class="metrics" aria-label="資源摘要">
          ${this.metric("CPU", this.number(resources.cpu_percent), "%")}
          ${this.metric("記憶體", this.number(resources.memory_percent), "%")}
          ${this.metric("磁碟", this.number(health.disk_percent), "%")}
          ${this.metric("負載", this.number(health.load_1, 2))}
        </div>

        ${expanded ? `
          <div class="details">
            <dl>
              <div><dt>節點 ID</dt><dd>${this.escape(id)}</dd></div>
              <div><dt>Agent</dt><dd>${this.escape(node.agent_version || "未知")}</dd></div>
              <div><dt>作業系統</dt><dd>${this.escape(item.streams?.metadata?.data?.os_name || "未知")}</dd></div>
              <div><dt>運行時間</dt><dd>${this.escape(this.number(health.uptime_hours))} 小時</dd></div>
              <div><dt>安全更新</dt><dd>${this.escape(health.security_updates ?? "未知")}</dd></div>
              <div><dt>異常服務</dt><dd>${this.escape(failedServices)}</dd></div>
              <div><dt>Docker</dt><dd>${this.escape(health.docker_running ?? "未知")} 個執行中</dd></div>
              <div><dt>資料狀態</dt><dd>${this.escape(stale || "最新")}</dd></div>
            </dl>
          </div>
        ` : ""}
      </article>
    `;
  }

  emptyState(message, detail) {
    return `
      <div class="empty" role="status">
        <span aria-hidden="true">◇</span>
        <strong>${this.escape(message)}</strong>
        <p>${this.escape(detail)}</p>
      </div>
    `;
  }

  render() {
    if (!this.shadowRoot) return;
    const state = this._hass?.states?.[this._config.entity];
    const nodes = Array.isArray(state?.attributes?.nodes)
      ? state.attributes.nodes
      : [];
    const visible = this.visibleNodes(nodes);
    const online = Number(state?.attributes?.online_count || 0);
    const problems = Number(state?.attributes?.problem_count || 0);

    let body;
    if (!this._hass) {
      body = this.emptyState("正在載入", "等待 Home Assistant 提供資料。");
    } else if (!state) {
      body = this.emptyState(
        "找不到 Fleet 實體",
        `請確認 Controller 已建立 ${this._config.entity}。`
      );
    } else if (nodes.length === 0) {
      body = this.emptyState(
        "尚未加入 VPS",
        "請先從 Controller 產生節點註冊資料。"
      );
    } else if (visible.length === 0) {
      body = this.emptyState("沒有符合的節點", "請調整搜尋文字或狀態篩選。");
    } else {
      body = `<div class="node-list">${visible.map((node) => this.nodeCard(node)).join("")}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --fleet-ok: #30a46c;
          --fleet-warning: #d99a16;
          --fleet-critical: #df4b4b;
          --fleet-offline: #77808f;
          --fleet-stale: #8a63d2;
          display: block;
          color: var(--primary-text-color);
        }
        * { box-sizing: border-box; }
        ha-card {
          overflow: hidden;
          padding: 20px;
          background:
            radial-gradient(circle at 95% 0%, color-mix(in srgb, var(--primary-color) 13%, transparent), transparent 34%),
            var(--ha-card-background, var(--card-background-color));
        }
        .header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 18px;
        }
        .title h2 { margin: 0; font-size: 1.35rem; line-height: 1.2; }
        .title p { margin: 6px 0 0; color: var(--secondary-text-color); font-size: .88rem; }
        .totals { display: flex; gap: 8px; }
        .total {
          min-width: 68px;
          padding: 9px 11px;
          border: 1px solid var(--divider-color);
          border-radius: 14px;
          text-align: center;
          background: color-mix(in srgb, var(--card-background-color) 84%, transparent);
        }
        .total strong { display: block; font-size: 1.05rem; }
        .total span { color: var(--secondary-text-color); font-size: .72rem; }
        .controls {
          display: grid;
          grid-template-columns: minmax(140px, 1fr) auto;
          gap: 10px;
          margin-bottom: 16px;
        }
        .search {
          min-height: 44px;
          width: 100%;
          padding: 0 14px;
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          color: var(--primary-text-color);
          background: var(--secondary-background-color);
          font: inherit;
        }
        .filters {
          display: flex;
          gap: 6px;
          overflow-x: auto;
          scrollbar-width: none;
        }
        .filters button {
          min-height: 44px;
          padding: 0 14px;
          border: 1px solid var(--divider-color);
          border-radius: 12px;
          color: var(--secondary-text-color);
          background: transparent;
          font: inherit;
          white-space: nowrap;
          cursor: pointer;
        }
        .filters button[aria-pressed="true"] {
          color: var(--primary-text-color);
          border-color: var(--primary-color);
          background: color-mix(in srgb, var(--primary-color) 14%, transparent);
        }
        .node-list { display: grid; gap: 10px; }
        .node {
          --status-color: var(--fleet-offline);
          border: 1px solid var(--divider-color);
          border-left: 4px solid var(--status-color);
          border-radius: 16px;
          background: color-mix(in srgb, var(--secondary-background-color) 72%, transparent);
          overflow: hidden;
        }
        .status-normal { --status-color: var(--fleet-ok); }
        .status-warning { --status-color: var(--fleet-warning); }
        .status-critical { --status-color: var(--fleet-critical); }
        .status-offline { --status-color: var(--fleet-offline); }
        .status-stale { --status-color: var(--fleet-stale); }
        .node-summary {
          display: grid;
          grid-template-columns: 36px minmax(0, 1fr) auto 30px;
          align-items: center;
          gap: 10px;
          min-height: 64px;
          width: 100%;
          padding: 10px 12px;
          border: 0;
          color: inherit;
          background: transparent;
          text-align: left;
          font: inherit;
          cursor: pointer;
        }
        .node-summary:focus-visible, .filters button:focus-visible, .search:focus-visible {
          outline: 3px solid color-mix(in srgb, var(--primary-color) 55%, transparent);
          outline-offset: 2px;
        }
        .status-symbol {
          display: grid;
          place-items: center;
          width: 32px;
          height: 32px;
          border-radius: 11px;
          color: white;
          background: var(--status-color);
          font-weight: 800;
        }
        .identity, .status-copy { min-width: 0; display: flex; flex-direction: column; }
        .identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .identity span, .status-copy small {
          margin-top: 3px;
          color: var(--secondary-text-color);
          font-size: .76rem;
        }
        .status-copy { text-align: right; }
        .status-copy strong { color: var(--status-color); }
        .chevron { text-align: center; font-size: 1.2rem; }
        .metrics {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 1px;
          border-top: 1px solid var(--divider-color);
          background: var(--divider-color);
        }
        .metric { padding: 10px 12px; background: var(--ha-card-background, var(--card-background-color)); }
        .metric-label { display: block; margin-bottom: 3px; color: var(--secondary-text-color); font-size: .7rem; }
        .metric strong { font-size: .95rem; }
        .details { padding: 12px; border-top: 1px solid var(--divider-color); }
        dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 18px; margin: 0; }
        dl div { min-width: 0; }
        dt { color: var(--secondary-text-color); font-size: .72rem; }
        dd { margin: 3px 0 0; overflow-wrap: anywhere; font-size: .86rem; }
        .empty {
          display: grid;
          place-items: center;
          min-height: 190px;
          padding: 24px;
          border: 1px dashed var(--divider-color);
          border-radius: 16px;
          color: var(--secondary-text-color);
          text-align: center;
        }
        .empty span { font-size: 2rem; }
        .empty strong { margin-top: 10px; color: var(--primary-text-color); }
        .empty p { margin: 6px 0 0; max-width: 36ch; }
        .version { margin-top: 12px; color: var(--secondary-text-color); font-size: .65rem; text-align: right; opacity: .65; }
        @media (max-width: 600px) {
          ha-card { padding: 14px; }
          .header { align-items: stretch; flex-direction: column; }
          .totals { width: 100%; }
          .total { flex: 1; }
          .controls { grid-template-columns: 1fr; }
          .metrics { grid-template-columns: repeat(2, 1fr); }
          .node-summary { grid-template-columns: 34px minmax(0, 1fr) 28px; }
          .status-copy { grid-column: 2; text-align: left; }
          .chevron { grid-column: 3; grid-row: 1 / span 2; }
          dl { grid-template-columns: 1fr; }
        }
        @media (prefers-reduced-motion: no-preference) {
          .node, .filters button { transition: border-color .18s ease, background-color .18s ease; }
        }
      </style>
      <ha-card>
        <div class="header">
          <div class="title">
            <h2>${this.escape(this._config.title)}</h2>
            <p>異常優先 · ${this.escape(nodes.length)} 個節點</p>
          </div>
          <div class="totals" aria-label="Fleet 摘要">
            <div class="total"><strong>${this.escape(online)}</strong><span>在線</span></div>
            <div class="total"><strong>${this.escape(problems)}</strong><span>需注意</span></div>
          </div>
        </div>
        <div class="controls">
          <input class="search" type="search" placeholder="搜尋名稱、供應商或標籤" aria-label="搜尋 VPS" value="${this.escape(this._query)}">
          <div class="filters" role="group" aria-label="狀態篩選">
            <button type="button" data-filter="all" aria-pressed="${this._filter === "all"}">全部</button>
            <button type="button" data-filter="problems" aria-pressed="${this._filter === "problems"}">需注意</button>
            <button type="button" data-filter="offline" aria-pressed="${this._filter === "offline"}">離線</button>
          </div>
        </div>
        ${body}
        <div class="version">Fleet Card ${FLEET_CARD_VERSION}</div>
      </ha-card>
    `;

    this.shadowRoot.querySelector(".search")?.addEventListener("input", (event) => {
      this._query = event.target.value;
      this.render();
      const input = this.shadowRoot.querySelector(".search");
      input?.focus();
      input?.setSelectionRange(this._query.length, this._query.length);
    });
    this.shadowRoot.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        this._filter = button.dataset.filter;
        this.render();
      });
    });
    this.shadowRoot.querySelectorAll("[data-node-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.nodeId;
        if (this._expanded.has(id)) this._expanded.delete(id);
        else this._expanded.add(id);
        this.render();
      });
    });
  }
}

if (!customElements.get("vps-sentinel-fleet-card")) {
  customElements.define("vps-sentinel-fleet-card", VpsSentinelFleetCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "vps-sentinel-fleet-card")) {
  window.customCards.push({
    type: "vps-sentinel-fleet-card",
    name: "VPS Sentinel Fleet Card",
    description: "異常優先的多 VPS 統一監控介面",
    preview: true,
  });
}
