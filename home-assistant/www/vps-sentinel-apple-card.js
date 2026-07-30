const CARD_VERSION = "0.8.0-preview";

class VpsSentinelAppleCard extends HTMLElement {
  setConfig(config) {
    const required = ["cpu", "memory", "disk", "health", "reporting"];
    for (const key of required) {
      if (!config[key]) throw new Error(`缺少必要實體：${key}`);
    }
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._build();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._nodes) this._update();
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return {
      cpu: "sensor.vps_cpu_percent",
      memory: "sensor.vps_memory_percent",
      disk: "sensor.vps_disk_percent",
      health: "sensor.vps_health_status",
      reporting: "binary_sensor.vps_reporting",
    };
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
            "SF Pro Text", "Helvetica Neue", sans-serif;
          -webkit-font-smoothing: antialiased;
          --vs-blue: #0a84ff;
          --vs-purple: #bf5af2;
          --vs-green: #30d158;
          --vs-orange: #ff9f0a;
          --vs-red: #ff453a;
        }
        ha-card {
          overflow: hidden;
          padding: clamp(18px, 4vw, 30px);
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 12%, transparent);
          border-radius: clamp(24px, 5vw, 34px);
          background:
            radial-gradient(circle at 8% 0%, rgba(10,132,255,.16), transparent 34%),
            radial-gradient(circle at 92% 8%, rgba(191,90,242,.14), transparent 32%),
            color-mix(in srgb, var(--card-background-color) 88%, transparent);
          box-shadow: 0 20px 55px rgba(0,0,0,.16);
          backdrop-filter: saturate(150%) blur(24px);
          -webkit-backdrop-filter: saturate(150%) blur(24px);
        }
        .header {
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 22px;
        }
        .eyebrow {
          margin-bottom: 4px;
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 650;
          letter-spacing: .08em;
          text-transform: uppercase;
        }
        h1 {
          margin: 0;
          font-size: clamp(26px, 5vw, 38px);
          font-weight: 760;
          letter-spacing: -.035em;
          line-height: 1.05;
        }
        .status {
          flex: 0 0 auto;
          padding: 8px 12px;
          border-radius: 999px;
          background: color-mix(in srgb, var(--vs-green) 16%, transparent);
          color: var(--vs-green);
          font-size: 13px;
          font-weight: 700;
          transition: color .35s ease, background .35s ease;
        }
        .status.warning {
          color: var(--vs-orange);
          background: color-mix(in srgb, var(--vs-orange) 16%, transparent);
        }
        .status.critical, .status.offline {
          color: var(--vs-red);
          background: color-mix(in srgb, var(--vs-red) 16%, transparent);
        }
        .resources {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
          gap: clamp(10px, 2.5vw, 16px);
        }
        .resource {
          position: relative;
          min-width: 0;
          padding: 16px;
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
          border-radius: 22px;
          background: color-mix(in srgb, var(--card-background-color) 82%, transparent);
          cursor: pointer;
          transition: transform .22s ease, background .22s ease;
        }
        .resource:active { transform: scale(.975); }
        .resource:hover {
          background: color-mix(in srgb, var(--card-background-color) 94%, transparent);
        }
        .resource-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 20px;
        }
        .label {
          color: var(--secondary-text-color);
          font-size: 14px;
          font-weight: 650;
        }
        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--accent);
          box-shadow: 0 0 18px color-mix(in srgb, var(--accent) 65%, transparent);
        }
        .value {
          margin-bottom: 14px;
          font-size: clamp(28px, 6vw, 40px);
          font-variant-numeric: tabular-nums;
          font-weight: 740;
          letter-spacing: -.04em;
          line-height: 1;
        }
        .unit {
          margin-left: 2px;
          color: var(--secondary-text-color);
          font-size: .48em;
          letter-spacing: 0;
        }
        .track {
          height: 8px;
          overflow: hidden;
          border-radius: 999px;
          background: color-mix(in srgb, var(--accent) 15%, transparent);
        }
        .fill {
          width: calc(var(--value, 0) * 1%);
          height: 100%;
          border-radius: inherit;
          background: var(--accent);
          box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 52%, transparent);
          transition: width .7s cubic-bezier(.22, 1, .36, 1);
        }
        .footer {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 16px;
        }
        .pill {
          padding: 7px 10px;
          border-radius: 999px;
          background: color-mix(in srgb, var(--primary-text-color) 7%, transparent);
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 620;
        }
        .pill.live { color: var(--vs-green); }
        .pill.stale { color: var(--vs-red); }
        @media (max-width: 430px) {
          ha-card { padding: 16px; border-radius: 26px; }
          .header { align-items: center; margin-bottom: 16px; }
          .resources { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
          .resource { padding: 12px 10px; border-radius: 18px; }
          .resource-top { margin-bottom: 14px; }
          .label { font-size: 12px; }
          .value { font-size: clamp(22px, 8vw, 30px); }
          .track { height: 6px; }
        }
        @media (max-width: 340px) {
          .resources { grid-template-columns: 1fr; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            scroll-behavior: auto !important;
            transition-duration: .01ms !important;
            animation-duration: .01ms !important;
          }
        }
      </style>
      <ha-card>
        <div class="header">
          <div>
            <div class="eyebrow">VPS SENTINEL</div>
            <h1></h1>
          </div>
          <div class="status">讀取中</div>
        </div>
        <div class="resources"></div>
        <div class="footer">
          <span class="pill reporting">資料讀取中</span>
        </div>
      </ha-card>`;

    const resources = [
      ["cpu", "CPU", "var(--vs-blue)"],
      ["memory", "記憶體", "var(--vs-purple)"],
      ["disk", "磁碟", "var(--vs-green)"],
    ];
    const container = this.shadowRoot.querySelector(".resources");
    this._nodes = {
      status: this.shadowRoot.querySelector(".status"),
      reporting: this.shadowRoot.querySelector(".reporting"),
      resources: {},
    };
    this.shadowRoot.querySelector("h1").textContent =
      this._config.title || "主機狀態";
    for (const [key, label, color] of resources) {
      const node = document.createElement("div");
      node.className = "resource";
      node.style.setProperty("--accent", color);
      node.innerHTML = `
        <div class="resource-top"><span class="label"></span><span class="dot"></span></div>
        <div class="value"><span class="number">—</span><span class="unit">%</span></div>
        <div class="track"><div class="fill"></div></div>`;
      node.querySelector(".label").textContent = label;
      node.addEventListener("click", () => this._moreInfo(this._config[key]));
      container.appendChild(node);
      this._nodes.resources[key] = node;
    }
    if (this._hass) this._update();
  }

  _state(entityId) {
    return this._hass?.states?.[entityId];
  }

  _number(entityId) {
    const value = Number.parseFloat(this._state(entityId)?.state);
    return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  }

  _update() {
    for (const key of ["cpu", "memory", "disk"]) {
      const value = this._number(this._config[key]);
      const node = this._nodes.resources[key];
      node.style.setProperty("--value", value ?? 0);
      node.querySelector(".number").textContent = value === null ? "—" : value.toFixed(1);
    }

    const health = this._state(this._config.health)?.state ?? "資料不可用";
    const status = this._nodes.status;
    status.textContent = health;
    status.className = "status";
    if (health === "需要留意") status.classList.add("warning");
    else if (health === "需要處理") status.classList.add("critical");
    else if (health === "unavailable" || health === "資料不可用") {
      status.classList.add("offline");
    }

    const reporting = this._state(this._config.reporting)?.state;
    const pill = this._nodes.reporting;
    const live = reporting === "on";
    pill.textContent = live ? "● 資料持續更新" : "● 資料已停止更新";
    pill.className = `pill reporting ${live ? "live" : "stale"}`;
  }

  _moreInfo(entityId) {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        bubbles: true,
        composed: true,
        detail: { entityId },
      }),
    );
  }
}

if (!customElements.get("vps-sentinel-apple-card")) {
  customElements.define("vps-sentinel-apple-card", VpsSentinelAppleCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "vps-sentinel-apple-card",
  name: "VPS Sentinel Apple Card",
  description: "自適應、低負載的 VPS 狀態卡片",
  preview: true,
});

console.info(`%c VPS Sentinel Apple Card ${CARD_VERSION} `, "color:#0a84ff;font-weight:700");
