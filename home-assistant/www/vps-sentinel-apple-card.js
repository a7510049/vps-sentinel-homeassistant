const CARD_VERSION = "0.9.2";

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
          animation: vs-card-in .42s cubic-bezier(.22, 1, .36, 1) both;
        }
        @keyframes vs-card-in {
          from { opacity: 0; transform: translateY(8px) scale(.992); }
          to { opacity: 1; transform: translateY(0) scale(1); }
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
          align-items: flex-end;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 22px;
        }
        .header-status {
          display: flex;
          flex: 0 0 auto;
          align-items: flex-end;
        }
        .health-card {
          --health-color: var(--vs-green);
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          gap: 9px;
          align-items: center;
          min-width: 108px;
          padding: 9px 12px;
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 11%, transparent);
          border-radius: 17px;
          background:
            linear-gradient(
              145deg,
              color-mix(in srgb, var(--primary-text-color) 7%, transparent),
              color-mix(in srgb, var(--card-background-color) 84%, transparent)
            );
          box-shadow: inset 0 1px 0 rgba(255,255,255,.045);
          transition: border-color .35s ease, background .35s ease;
        }
        .health-card.warning { --health-color: var(--vs-orange); }
        .health-card.critical,
        .health-card.offline,
        .health-card.stale { --health-color: var(--vs-red); }
        .health-card.warning,
        .health-card.critical,
        .health-card.offline,
        .health-card.stale {
          border-color: color-mix(in srgb, var(--health-color) 28%, transparent);
          background:
            linear-gradient(
              145deg,
              color-mix(in srgb, var(--health-color) 15%, transparent),
              color-mix(in srgb, var(--card-background-color) 86%, transparent)
            );
        }
        .health-orb {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--health-color);
          box-shadow: 0 0 12px color-mix(in srgb, var(--health-color) 62%, transparent);
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
          color: var(--primary-text-color);
          font-size: 12px;
          font-weight: 720;
          line-height: 1.2;
          white-space: nowrap;
        }
        .health-card.warning .status,
        .health-card.critical .status,
        .health-card.offline .status,
        .health-card.stale .status { color: var(--health-color); }
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
          box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
          transition: transform .22s ease, background .22s ease, border-color .22s ease, box-shadow .22s ease;
          will-change: transform;
          -webkit-tap-highlight-color: transparent;
          touch-action: manipulation;
        }
        .resource:active { transform: scale(.975); }
        .resource.pressing { transform: scale(.975); }
        .resource:hover {
          background: color-mix(in srgb, var(--card-background-color) 94%, transparent);
          border-color: color-mix(in srgb, var(--accent) 34%, transparent);
          box-shadow: 0 10px 24px color-mix(in srgb, var(--accent) 12%, transparent), inset 0 1px 0 rgba(255,255,255,.045);
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
          font-size: 10px;
          font-weight: 620;
          line-height: 1.2;
          white-space: nowrap;
        }
        .reporting.live { color: var(--secondary-text-color); }
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
          transition: transform .2s ease, border-color .2s ease, background .2s ease;
          will-change: transform;
          -webkit-tap-highlight-color: transparent;
          touch-action: manipulation;
        }
        .insight:hover {
          transform: translateY(-1px);
          border-color: color-mix(in srgb, var(--accent) 34%, transparent);
        }
        .insight:active,
        .insight.pressing {
          transform: scale(.965);
          border-color: color-mix(in srgb, var(--accent) 45%, transparent);
          background: color-mix(in srgb, var(--accent) 20%, transparent);
        }
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
        .maintenance {
          display: none;
          margin-top: 18px;
          padding: 16px;
          border: 1px solid color-mix(in srgb, var(--vs-blue) 18%, transparent);
          border-radius: 22px;
          background:
            linear-gradient(
              135deg,
              color-mix(in srgb, var(--vs-blue) 10%, transparent),
              color-mix(in srgb, var(--vs-purple) 8%, transparent),
              color-mix(in srgb, var(--card-background-color) 90%, transparent)
            );
        }
        .maintenance.visible { display: block; }
        .maintenance-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 10px;
        }
        .maintenance-title { font-size: 14px; font-weight: 720; }
        .maintenance-state {
          display: none;
        }
        .maintenance-progress {
          display: none;
          overflow: hidden;
          position: relative;
          height: 30px;
          margin-bottom: 10px;
          border: 1px solid color-mix(in srgb, var(--progress-color, var(--vs-blue)) 24%, transparent);
          border-radius: 11px;
          background: color-mix(in srgb, var(--progress-color, var(--vs-blue)) 8%, transparent);
          color: var(--primary-text-color);
        }
        .maintenance-progress.visible { display: block; }
        .maintenance-progress-fill {
          width: var(--progress, 0%);
          height: 100%;
          border-radius: inherit;
          background: linear-gradient(90deg, color-mix(in srgb, var(--progress-color) 84%, transparent), color-mix(in srgb, var(--progress-color) 36%, transparent));
          transition: width .45s cubic-bezier(.22, 1, .36, 1), background .3s ease;
        }
        .maintenance-progress.sending .maintenance-progress-fill,
        .maintenance-progress.running .maintenance-progress-fill {
          width: 38%;
          animation: vs-maintenance-progress 1.25s ease-in-out infinite;
        }
        @keyframes vs-maintenance-progress {
          0% { transform: translateX(-120%); }
          100% { transform: translateX(290%); }
        }
        .maintenance-progress-label {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          padding: 0 11px;
          overflow: hidden;
          font-size: 11px;
          font-weight: 700;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .actions {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          overflow: hidden;
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 11%, transparent);
          border-radius: 16px;
          background: color-mix(in srgb, var(--card-background-color) 78%, transparent);
        }
        .action {
          min-width: 0;
          padding: 12px 7px 11px;
          border: 0;
          border-radius: 0;
          background:
            linear-gradient(
              180deg,
              color-mix(in srgb, var(--accent) 10%, transparent),
              transparent 70%
            );
          box-shadow: inset 0 2px 0 color-mix(in srgb, var(--accent) 72%, transparent);
          color: var(--primary-text-color);
          font: inherit;
          font-size: 12px;
          font-weight: 680;
          cursor: pointer;
          transition: background .2s ease, opacity .2s ease, color .2s ease;
        }
        .action + .action {
          border-left: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
        }
        .action:hover {
          background: color-mix(in srgb, var(--accent) 13%, transparent);
        }
        .action:active {
          background: color-mix(in srgb, var(--accent) 19%, transparent);
        }
        .action:focus-visible,
        .resource:focus-visible,
        .insight:focus-visible {
          outline: 2px solid var(--accent, var(--vs-blue));
          outline-offset: -2px;
        }
        .action:disabled { cursor: wait; opacity: .45; }
        .maintenance.busy .actions { opacity: .7; }
        dialog {
          width: min(330px, calc(100% - 32px));
          padding: 0;
          border: 1px solid color-mix(in srgb, var(--primary-text-color) 13%, transparent);
          border-radius: 24px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          box-shadow: 0 24px 80px rgba(0,0,0,.42);
        }
        dialog::backdrop {
          background: rgba(0,0,0,.48);
          backdrop-filter: blur(8px);
        }
        .confirm-copy { padding: 22px 22px 14px; }
        .confirm-title { margin-bottom: 8px; font-size: 20px; font-weight: 750; }
        .confirm-message {
          color: var(--secondary-text-color);
          font-size: 14px;
          line-height: 1.5;
        }
        .confirm-actions {
          display: grid;
          grid-template-columns: 1fr 1fr;
          border-top: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
        }
        .confirm-actions button {
          padding: 14px;
          border: 0;
          background: transparent;
          color: var(--vs-blue);
          font: inherit;
          font-weight: 680;
        }
        .confirm-actions button + button {
          border-left: 1px solid color-mix(in srgb, var(--primary-text-color) 10%, transparent);
        }
        .confirm-actions .danger { color: var(--vs-red); }
        @media (max-width: 430px) {
          ha-card { padding: 16px; border-radius: 26px; }
          .header { align-items: flex-end; margin-bottom: 16px; }
          .header-status {
            flex: 0 0 calc((100% - 16px) / 3);
            width: calc((100% - 16px) / 3);
          }
          .health-card {
            width: 100%;
            min-width: 0;
            padding-inline: 9px;
          }
          .resources { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
          .resource { padding: 12px 10px; border-radius: 18px; }
          .resource-top { margin-bottom: 14px; }
          .label { font-size: 12px; }
          .value { font-size: clamp(22px, 8vw, 30px); }
          .track { height: 6px; }
          .insights { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .maintenance { margin-top: 16px; padding: 14px; }
          .action { padding-inline: 4px; font-size: 11px; }
        }
        @media (max-width: 340px) {
          .header-status { flex-basis: auto; width: auto; }
          .health-card { width: auto; }
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
        <div class="maintenance">
          <div class="maintenance-head">
            <div class="maintenance-title">主機維護</div>
            <div class="maintenance-state">等待操作</div>
          </div>
          <div class="actions">
            <button class="action" data-action="refresh" style="--accent:var(--vs-blue)">檢查更新</button>
            <button class="action" data-action="security_update" style="--accent:var(--vs-orange)">安全更新</button>
            <button class="action" data-action="reboot" style="--accent:var(--vs-red)">重新啟動</button>
          </div>
        </div>
        <dialog>
          <div class="confirm-copy">
            <div class="confirm-title"></div>
            <div class="confirm-message"></div>
          </div>
          <div class="confirm-actions">
            <button data-confirm="cancel">取消</button>
            <button data-confirm="ok">繼續</button>
          </div>
        </dialog>
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
      maintenance: this.shadowRoot.querySelector(".maintenance"),
      maintenanceState: this.shadowRoot.querySelector(".maintenance-state"),
      dialog: this.shadowRoot.querySelector("dialog"),
      resources: {},
      insights: {},
    };
    const maintenanceProgress = document.createElement("div");
    maintenanceProgress.className = "maintenance-progress";
    maintenanceProgress.setAttribute("role", "status");
    maintenanceProgress.setAttribute("aria-live", "polite");
    maintenanceProgress.innerHTML =
      '<div class="maintenance-progress-fill"></div><div class="maintenance-progress-label"></div>';
    this._nodes.maintenance.insertBefore(
      maintenanceProgress,
      this._nodes.maintenance.querySelector(".actions"),
    );
    this._nodes.maintenanceProgress = maintenanceProgress;
    this._nodes.maintenanceProgressLabel = maintenanceProgress.querySelector(
      ".maintenance-progress-label",
    );
    for (const button of this.shadowRoot.querySelectorAll(".action")) {
      button.addEventListener("click", () => this._confirmAction(button.dataset.action));
    }
    this.shadowRoot.querySelector('[data-confirm="cancel"]')
      .addEventListener("click", () => this._nodes.dialog.close());
    this.shadowRoot.querySelector('[data-confirm="ok"]')
      .addEventListener("click", () => this._runConfirmedAction());
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
      this._bindMoreInfo(node, this._config[key]);
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
      this._bindMoreInfo(node, this._config[key]);
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
    pill.textContent = live ? "同步正常" : "同步中斷";
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

    const maintenanceEntity = this._state(this._config.maintenance);
    const maintenance = this._nodes.maintenance;
    const maintenanceVisible = Boolean(
      this._config.commandTopic && maintenanceEntity,
    );
    maintenance.classList.toggle("visible", maintenanceVisible);
    if (maintenanceVisible) {
      const backendState = maintenanceEntity.state;
      const message = maintenanceEntity.attributes?.message;
      const action = maintenanceEntity.attributes?.action;
      if (backendState !== "idle") this._localMaintenanceState = null;
      if (
        this._localMaintenanceState
        && Date.now() > this._localMaintenanceState.expiresAt
      ) this._localMaintenanceState = null;
      const localState = this._localMaintenanceState;
      const state = backendState === "idle" && localState
        ? localState.state
        : backendState;
      const progressMessage = backendState === "idle" && localState
        ? localState.message
        : message;
      const progressAction = backendState === "idle" && localState
        ? localState.action
        : action;
      const displayState = this._maintenanceDisplayState(
        state,
        progressAction,
        maintenanceEntity.attributes?.updated_at,
      );
      const busy = displayState === "running" || displayState === "sending";
      this._setMaintenanceProgress(
        displayState,
        this._maintenanceMessage(displayState, progressAction, progressMessage),
      );
      for (const button of maintenance.querySelectorAll(".action")) {
        button.disabled = busy;
      }
      maintenance.classList.toggle("busy", busy);
    }
  }

  _maintenanceDisplayState(state, action, updatedAt) {
    const temporary = new Set([
      "success", "scheduled", "failed", "rejected", "cooldown", "busy",
    ]);
    if (!temporary.has(state)) return state;
    const key = `${state}:${action || "none"}:${updatedAt || "local"}`;
    if (this._dismissedMaintenanceEvent === key) return "idle";
    if (this._maintenanceDismissTimerKey !== key) {
      clearTimeout(this._maintenanceDismissTimer);
      this._maintenanceDismissTimerKey = key;
      this._maintenanceDismissTimer = setTimeout(() => {
        this._dismissedMaintenanceEvent = key;
        this._maintenanceDismissTimerKey = null;
        this._update();
      }, 5000);
    }
    return state;
  }

  _maintenanceMessage(state, action, message) {
    const name = {
      refresh: "檢查更新",
      security_update: "安全更新",
      reboot: "重新啟動",
    }[action] || "主機維護";
    if (state === "sending") return `正在送出「${name}」…`;
    if (state === "running") return `正在${name}，請稍候…`;
    if (state === "success") return `完成：${message || name}`;
    if (state === "scheduled") return message || "已安排重新啟動";
    if (state === "failed") return `${name}未完成：${message || "請稍後再試"}`;
    if (state === "cooldown") {
      const seconds = String(message || "").match(/(\d+)\s*秒/)?.[1];
      return seconds
        ? `「${name}」可在 ${seconds} 秒後再次執行`
        : `「${name}」正在冷卻，請稍後再試`;
    }
    if (state === "rejected") return `「${name}」已拒絕：${message || "請重新操作"}`;
    if (state === "busy") return message || "已有另一個維護操作正在進行";
    if (state === "disabled") return "遠端維護尚未啟用";
    return message || "";
  }

  _setMaintenanceProgress(state, message) {
    const progress = this._nodes.maintenanceProgress;
    const labels = {
      sending: "正在送出操作…",
      running: "正在處理，請稍候…",
      success: "操作完成",
      scheduled: "已安排重新啟動",
      failed: "操作未完成",
      rejected: "操作已拒絕",
      cooldown: "請稍候再試",
      busy: "已有操作正在進行",
      disabled: "遠端維護尚未啟用",
    };
    const colors = {
      sending: "var(--vs-blue)",
      running: "var(--vs-blue)",
      success: "var(--vs-green)",
      scheduled: "var(--vs-purple)",
      failed: "var(--vs-red)",
      rejected: "var(--vs-red)",
      cooldown: "var(--vs-orange)",
      busy: "var(--vs-orange)",
      disabled: "var(--vs-orange)",
    };
    const visible = state && state !== "idle";
    progress.className = `maintenance-progress ${visible ? "visible" : ""} ${state || ""}`.trim();
    progress.style.setProperty("--progress-color", colors[state] || "var(--vs-blue)");
    progress.style.setProperty(
      "--progress",
      state === "sending" || state === "running" ? "38%" : "100%",
    );
    this._nodes.maintenanceProgressLabel.textContent =
      message || labels[state] || "";
  }

  _maintenanceLabel(state) {
    return {
      idle: "等待操作",
      running: "處理中",
      success: "已完成",
      scheduled: "已排程",
      failed: "執行失敗",
      rejected: "操作遭拒",
      cooldown: "請稍後再試",
      busy: "已有操作執行中",
    }[state] || "等待操作";
  }

  _confirmAction(action) {
    const details = {
      refresh: ["檢查更新", "只更新套件清單，不會安裝或重新啟動。"],
      security_update: [
        "安裝安全更新",
        "只安裝 Ubuntu 安全更新；完成後可能會建議重新啟動。",
      ],
      reboot: [
        "重新啟動主機",
        "主機將在 30 秒後重新啟動，期間 Home Assistant 會暫時離線。",
      ],
    }[action];
    if (!details) return;
    this._pendingAction = action;
    this._nodes.dialog.querySelector(".confirm-title").textContent = details[0];
    this._nodes.dialog.querySelector(".confirm-message").textContent = details[1];
    const confirm = this._nodes.dialog.querySelector('[data-confirm="ok"]');
    confirm.textContent = action === "reboot" ? "重新啟動" : "繼續";
    confirm.classList.toggle("danger", action === "reboot");
    this._nodes.dialog.showModal();
  }

  async _runConfirmedAction() {
    const action = this._pendingAction;
    this._nodes.dialog.close();
    if (!action || !this._config.commandTopic || !this._hass) return;
    const requestId = globalThis.crypto?.randomUUID?.()
      || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    try {
      this._localMaintenanceState = {
        state: "sending",
        message: "正在送出操作…",
        at: Date.now(),
        action,
        expiresAt: Date.now() + 15000,
      };
      this._update();
      await this._hass.callService("mqtt", "publish", {
        topic: this._config.commandTopic,
        payload: JSON.stringify({
          action,
          request_id: requestId,
          issued_at: Date.now(),
        }),
        qos: 1,
        retain: false,
      });
      this._localMaintenanceState = {
        state: "sending",
        message: "命令已送出，等待主機回覆…",
        at: Date.now(),
        action,
        expiresAt: Date.now() + 15000,
      };
      this._update();
    } catch (_error) {
      this._localMaintenanceState = {
        state: "failed",
        message: "無法送出，請檢查 MQTT 權限",
        at: Date.now(),
        action,
        expiresAt: Date.now() + 5000,
      };
      this._update();
    } finally {
      this._pendingAction = null;
    }
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

  _bindMoreInfo(node, entityId) {
    node.setAttribute("role", "button");
    node.tabIndex = 0;
    let releaseTimer;
    const release = () => {
      clearTimeout(releaseTimer);
      releaseTimer = setTimeout(() => node.classList.remove("pressing"), 120);
    };
    node.addEventListener("pointerdown", () => {
      clearTimeout(releaseTimer);
      node.classList.add("pressing");
    });
    node.addEventListener("pointerup", release);
    node.addEventListener("pointercancel", release);
    node.addEventListener("pointerleave", release);
    node.addEventListener("click", () => this._moreInfo(entityId));
    node.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      this._moreInfo(entityId);
    });
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
