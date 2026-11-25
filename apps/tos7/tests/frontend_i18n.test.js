"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

globalThis.localStorage = {
  getItem: (key) => (key === "networkLocator.locale.v1" ? "en" : null),
  setItem: () => {}
};

require("../frontend/i18n.js");
const i18n = globalThis.NetworkLocatorI18n;

test("Chinese punctuation is localized in English mode", () => {
  assert.equal(i18n.t("："), ": ");
  assert.equal(i18n.t("，"), ", ");
  assert.equal(i18n.t("。"), ".");
  assert.equal(i18n.t("；"), "; ");
  assert.equal(i18n.t("、"), ", ");
  assert.equal(i18n.t("（"), " (");
  assert.equal(i18n.t("）"), ")");
});

test("English labels stay English and unknown keys pass through", () => {
  assert.equal(i18n.t("未知厂商"), "Unknown");
  assert.equal(i18n.t("（当前配置）"), " (current configuration)");
  assert.equal(i18n.t("192.0.2.1"), "192.0.2.1");
});
