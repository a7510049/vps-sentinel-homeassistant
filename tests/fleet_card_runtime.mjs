import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const CARD_PATH = new URL(
  "../home-assistant/www/vps-sentinel-fleet-card.js",
  import.meta.url,
);

class FakeElement {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.listeners = new Map();
    this.value = "";
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  dispatch(type, event = {}) {
    const listener = this.listeners.get(type);
    assert.ok(listener, `missing ${type} listener`);
    listener(event);
  }

  focus() {}

  setSelectionRange() {}
}

class FakeShadowRoot {
  constructor() {
    this.html = "";
    this.search = null;
    this.filters = [];
    this.nodes = [];
  }

  set innerHTML(value) {
    this.html = value;
    this.search = new FakeElement();
    this.filters = [...value.matchAll(/data-filter="([^"]+)"/g)].map(
      (match) => new FakeElement({ filter: match[1] }),
    );
    this.nodes = [...value.matchAll(/data-node-id="([^"]+)"/g)].map(
      (match) => new FakeElement({ nodeId: match[1] }),
    );
  }

  get innerHTML() {
    return this.html;
  }

  querySelector(selector) {
    return selector === ".search" ? this.search : null;
  }

  querySelectorAll(selector) {
    if (selector === "[data-filter]") return this.filters;
    if (selector === "[data-node-id]") return this.nodes;
    return [];
  }
}

class FakeHTMLElement {
  attachShadow() {
    this.shadowRoot = new FakeShadowRoot();
    return this.shadowRoot;
  }
}

const registry = new Map();
globalThis.HTMLElement = FakeHTMLElement;
globalThis.customElements = {
  define(name, constructor) {
    assert.equal(registry.has(name), false, `${name} registered twice`);
    registry.set(name, constructor);
  },
  get(name) {
    return registry.get(name);
  },
};
globalThis.window = { customCards: [] };

vm.runInThisContext(readFileSync(CARD_PATH, "utf8"), {
  filename: CARD_PATH.pathname,
});

const Card = customElements.get("vps-sentinel-fleet-card");
assert.equal(typeof Card, "function", "Fleet Card must register itself");
assert.deepEqual(Card.getStubConfig(), {
  entity: "sensor.vps_sentinel_fleet_nodes",
  title: "VPS Fleet",
});
assert.equal(window.customCards.length, 1, "card picker entry must be unique");

const card = new Card();
assert.throws(
  () => card.setConfig({ entity: "" }),
  /entity/,
  "an empty entity must be rejected",
);
card.setConfig({ title: "我的 VPS" });
assert.match(card.shadowRoot.innerHTML, /正在載入/);

card.hass = { states: {} };
assert.match(card.shadowRoot.innerHTML, /找不到 Fleet 實體/);

const entity = "sensor.vps_sentinel_fleet_nodes";
const nodes = [
  {
    status: "normal",
    node: {
      id: "alpha-01",
      display_name: "Alpha",
      provider: "Oracle",
      agent_version: "1.0-test",
    },
    last_received_at: "2026-08-08T08:00:00Z",
    streams: {
      resources: { data: { cpu_percent: 8, memory_percent: 20 } },
      health: { data: { disk_percent: 30, load_1: 0.2 } },
    },
  },
  {
    status: "critical",
    node: {
      id: "danger-01",
      display_name: '<img src=x onerror="alert(1)">',
      provider: "Test & Test",
      agent_version: "1.0-test",
    },
    last_received_at: "2026-08-08T08:00:00Z",
    streams: {
      resources: { data: { cpu_percent: 99, memory_percent: 98 } },
      health: { data: { disk_percent: 97, load_1: 10 } },
    },
  },
];

card.hass = {
  states: {
    [entity]: {
      state: "2",
      last_updated: "2026-08-08T08:01:00Z",
      attributes: {
        generated_at: "2026-08-08T08:01:00Z",
        node_count: 2,
        online_count: 2,
        problem_count: 1,
        nodes,
      },
    },
  },
};

let html = card.shadowRoot.innerHTML;
assert.ok(
  html.indexOf("danger-01") < html.indexOf("alpha-01"),
  "critical nodes must render before normal nodes",
);
assert.doesNotMatch(html, /<img src=x/);
assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
assert.match(html, /Test &amp; Test/);

const search = card.shadowRoot.querySelector(".search");
search.dispatch("input", { target: { value: "alpha" } });
html = card.shadowRoot.innerHTML;
assert.match(html, /alpha-01/);
assert.doesNotMatch(html, /danger-01/);

card.shadowRoot
  .querySelectorAll("[data-filter]")
  .find((button) => button.dataset.filter === "problems")
  .dispatch("click");
assert.match(card.shadowRoot.innerHTML, /沒有符合的節點/);

card._query = "";
card.render();
const criticalButton = card.shadowRoot
  .querySelectorAll("[data-node-id]")
  .find((button) => button.dataset.nodeId === "danger-01");
assert.ok(criticalButton, "critical node must expose an expansion control");
criticalButton.dispatch("click");
assert.equal(card._expanded.has("danger-01"), true);
assert.match(card.shadowRoot.innerHTML, /節點 ID/);

console.log("Fleet Card runtime contract: PASS");
