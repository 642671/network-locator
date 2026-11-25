"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("relayoutPanels tolerates a shell without legacy panel resizers", () => {
  globalThis.window = globalThis;
  globalThis.location = { pathname: "/", hash: "", search: "" };
  globalThis.localStorage = {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {}
  };
  globalThis.document = {
    readyState: "complete",
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: () => ({ style: {}, setAttribute: () => {}, appendChild: () => {} }),
    documentElement: {
      style: { setProperty: () => {} },
      setAttribute: () => {},
      getAttribute: () => "light"
    },
    body: { classList: { add: () => {}, remove: () => {}, toggle: () => {} } }
  };
  globalThis.matchMedia = () => ({ matches: false, addEventListener: () => {} });

  const source = fs.readFileSync(
    path.join(__dirname, "..", "frontend", "app.js"),
    "utf8"
  );
  vm.runInThisContext(source, { filename: "app.js" });

  assert.equal(typeof globalThis.NetworkLocatorApp.relayoutPanels, "function");
  assert.doesNotThrow(() => globalThis.NetworkLocatorApp.relayoutPanels());
});
