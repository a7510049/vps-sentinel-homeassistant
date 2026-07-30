const CARD_VERSION = "0.8.1";

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
            radial-gradient(circle at 5% 0%, rgba(10,132,255,.24), transparent 38%),
            radial-gradient(circle at 96% 4%, rgba(191,90,242,.22), transparent 38%),
            radial-gradient(circle at 55% 105%, rgba(48,209,88,.08), transparent 34%),
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
        .header-status {
          display: flex;
          flex: 0 0 auto;
          flex-direction: column;
          gap: 7px;
          align-items: flex-end;
        }
        .health-card {
          --health-color: var(--vs-green);
          display: grid;
          grid-template-columns: auto auto;
          gap: 10px;
          align-items: center;
          min-width: 112px;
          padding: 10px 13px;
          border: 1px solid color-mix(in srgb, var(--health-color) 24%, transparent);
          border-radius: 20px;
          background:
            linear-gradient(
              135deg,
              color-mix(in srgb, var(--health-color) 22%, transparent),
              color-mix(in srgb, var(--vs-blue) 8%, transparent)
            );
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.05),
            0 10px 30px color-mix(in srgb, var(--health-color) 9%, transparent);
          transition: border-color .35s ease, background .35s ease;
        }
        .health-card.warning { --health-color: var(--vs-orange); }
        .health-card.critical,
        .health-card.offline,
        .health-card.stale { --health-color: var(--vs-red); }
        .health-orb {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: var(--health-color);
          box-shadow: 0 0 16px color-mix(in srgb, var(--health-color) 75%, transparent);
        }
        .health-copy { min-width: 0; }
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
          color: var(--health-color);
          font-size: 13px;
          font-weight: 700;
          line-height: 1.2;
          white-space: nowrap;
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
          background:
            linear-gradient(
              145deg,
              color-mix(in srgb, var(--accent) 12%, transparent),
              color-mix(in srgb, var(--card-background-color) 88%, transparent) 58%
            );
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
        .reporting {
          margin-top: 3px;
          color: var(--secondary-text-color);
          font-size: 11px;
          font-weight: 620;
          line-height: 1.2;
          white-space: nowrap;
        }
        .reporting.live { color: color-mix(in srgb, var(--vs-green) 82%, white); }
        .reporting.stale { color: var(--vs-red); }
        .section-title {
          margin: 22px 2px 10px;
          color: var(--secondary-text-color);
          font-size: 13px;
          font-weight: 700;
          letter-spacing: .02em;
        }
        .insights {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 128px), 1fr));
          gap: 10px;
        }
        .insight {
          min-width: 0;
          padding: 13px 14px;
          border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
          border-radius: 18px;
          background:
            linear-gradient(
              145deg,
              color-mix(in srgb, var(--accent) 15%, transparent),
              color-mix(in srgb, var(--card-background-color) 86%, transparent)
            );
          cursor: pointer;
        }
        .insight-label {
          margin-bottom: 5px;
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 620;
        }
        .insight-value {
          overflow: hidden;
          font-size: 16px;
          font-weight: 720;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .insight-label::before {
          display: inline-block;
          width: 7px;
          height: 7px;
          margin-right: 7px;
          border-radius: 50%;
          background: var(--accent);
          box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 65%, transparent);
          content: "";
        }
        .alerts {
          display: none;
          gap: 8px;
          margin-top: 12px;
        }
        .alerts.visible { display: flex; flex-wrap: wrap; }
        .alert {
          padding: 8px 11px;
          border-radius: 999px;
          background: color-mix(in srgb, var(--vs-orange) 16%, transparent);
          color: var(--vs-orange);
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
        }
        .alert.critical {
          background: color-mix(in srgb, var(--vs-red) 16%, transparent);
          color: var(--vs-red);
        }
        .identity {
          display: none;
          grid-template-columns: auto minmax(0, 1fr);
          gap: 12px;
          align-items: center;
          margin-top: 12px;
          padding: 13px 14px;
          border-radius: 18px;
          border: 1px solid color-mix(in srgb, var(--vs-blue) 18%, transparent);
          background:
            linear-gradient(
              110deg,
              color-mix(in srgb, var(--vs-blue) 14%, transparent),
              color-mix(in srgb, var(--vs-purple) 12%, transparent),
              color-mix(in srgb, var(--card-background-color) 88%, transparent)
            );
        }
        .identity.visible { display: grid; }
        .flag {
          font-size: 30px;
          line-height: 1;
        }
        .identity-copy { min-width: 0; }
        .provider {
          overflow: hidden;
          font-size: 14px;
          font-weight: 720;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .os-name {
          overflow: hidden;
          margin-top: 3px;
          color: var(--secondary-text-color);
          font-size: 12px;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        @media (max-width: 430px) {
          ha-card { padding: 16px; border-radius: 26px; }
          .header { align-items: center; margin-bottom: 16px; }
          .resources { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
          .resource { padding: 12px 10px; border-radius: 18px; }
          .resource-top { margin-bottom: 14px; }
          .label { font-size: 12px; }
          .value { font-size: clamp(22px, 8vw, 30px); }
          .track { height: 6px; }
          .insights { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
          <div class="header-status">
            <div class="health-card">
              <span class="health-orb"></span>
              <div class="health-copy">
                <div class="status">讀取中</div>
                <div class="reporting">同步中</div>
              </div>
            </div>
          </div>
        </div>
        <div class="resources"></div>
        <div class="identity">
          <div class="flag">🌐</div>
          <div class="identity-copy">
            <div class="provider">—</div>
            <div class="os-name">—</div>
          </div>
        </div>
        <div class="section-title">系統資訊</div>
        <div class="insights"></div>
        <div class="alerts"></div>
      </ha-card>`;

    const resources = [
      ["cpu", "CPU", "var(--vs-blue)"],
      ["memory", "記憶體", "var(--vs-purple)"],
      ["disk", "磁碟", "var(--vs-green)"],
    ];
    const container = this.shadowRoot.querySelector(".resources");
    this._nodes = {
      status: this.shadowRoot.querySelector(".status"),
      healthCard: this.shadowRoot.querySelector(".health-card"),
      reporting: this.shadowRoot.querySelector(".reporting"),
      alerts: this.shadowRoot.querySelector(".alerts"),
      identity: this.shadowRoot.querySelector(".identity"),
      resources: {},
      insights: {},
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
    const insights = [
      ["uptime", "連續運作", "var(--vs-blue)"],
      ["updates", "待更新", "var(--vs-orange)"],
      ["containers", "容器", "#64d2ff"],
      ["bootTime", "上次開機", "var(--vs-purple)"],
    ];
    const insightContainer = this.shadowRoot.querySelector(".insights");
    for (const [key, label, color] of insights) {
      const node = document.createElement("div");
      node.className = "insight";
      node.style.setProperty("--accent", color);
      node.innerHTML =
        '<div class="insight-label"></div><div class="insight-value">—</div>';
      node.querySelector(".insight-label").textContent = label;
      node.addEventListener("click", () => this._moreInfo(this._config[key]));
      insightContainer.appendChild(node);
      this._nodes.insights[key] = node;
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
    const healthCard = this._nodes.healthCard;
    status.textContent = health;
    healthCard.className = "health-card";
    if (health === "需要留意") healthCard.classList.add("warning");
    else if (health === "需要處理") healthCard.classList.add("critical");
    else if (health === "unavailable" || health === "資料不可用") {
      healthCard.classList.add("offline");
    }

    const reporting = this._state(this._config.reporting)?.state;
    const pill = this._nodes.reporting;
    const live = reporting === "on";
    pill.textContent = live ? "● 同步正常" : "● 同步中斷";
    pill.className = `reporting ${live ? "live" : "stale"}`;
    healthCard.classList.toggle("stale", !live);

    const insightValues = {
      uptime: this._formatUptime(this._state(this._config.uptime)?.state),
      updates: this._plainState(this._config.updates, "0"),
      containers: this._plainState(this._config.containers),
      bootTime: this._formatTime(this._state(this._config.bootTime)?.state),
    };
    for (const [key, value] of Object.entries(insightValues)) {
      const node = this._nodes.insights[key];
      node.querySelector(".insight-value").textContent = value;
      node.hidden = !this._config[key];
    }

    const alerts = this._nodes.alerts;
    alerts.replaceChildren();
    this._appendAlert(
      alerts,
      this._config.serviceProblem,
      "服務需要留意",
      "critical",
    );
    this._appendAlert(
      alerts,
      this._config.rebootRequired,
      "建議重新啟動",
      "",
    );
    alerts.classList.toggle("visible", alerts.childElementCount > 0);

    const country = this._plainState(this._config.country);
    const provider = this._plainState(this._config.provider);
    const osName = this._plainState(this._config.osName);
    const identity = this._nodes.identity;
    identity.querySelector(".flag").textContent = this._countryFlag(country);
    identity.querySelector(".provider").textContent = provider;
    identity.querySelector(".os-name").textContent = osName;
    identity.classList.toggle(
      "visible",
      [country, provider, osName].some((value) => value !== "—"),
    );
  }

  _plainState(entityId, fallback = "—") {
    if (!entityId) return fallback;
    const state = this._state(entityId)?.state;
    return !state || ["unknown", "unavailable"].includes(state) ? fallback : state;
  }

  _formatUptime(value) {
    const hours = Number.parseFloat(value);
    if (!Number.isFinite(hours)) return "—";
    const days = Math.floor(hours / 24);
    const remaining = Math.floor(hours % 24);
    return days > 0 ? `${days}天 ${remaining}小時` : `${remaining}小時`;
  }

  _formatTime(value) {
    if (!value || ["unknown", "unavailable"].includes(value)) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-TW", {
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  _countryFlag(code) {
    if (!/^[A-Za-z]{2}$/.test(code)) return "🌐";
    return [...code.toUpperCase()]
      .map((letter) => String.fromCodePoint(127397 + letter.charCodeAt(0)))
      .join("");
  }

  _appendAlert(container, entityId, label, className) {
    if (!entityId || this._state(entityId)?.state !== "on") return;
    const node = document.createElement("div");
    node.className = `alert ${className}`.trim();
    node.textContent = label;
    node.addEventListener("click", () => this._moreInfo(entityId));
    container.appendChild(node);
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
if (!window.customCards.some((card) => card.type === "vps-sentinel-apple-card")) {
  window.customCards.push({
    type: "vps-sentinel-apple-card",
    name: "VPS Sentinel Apple Card",
    description: "自適應、低負載的 VPS 狀態卡片",
    preview: true,
  });
}

console.info(`%c VPS Sentinel Apple Card ${CARD_VERSION} `, "color:#0a84ff;font-weight:700");
