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

test("MAC lookup validation and badges are English", () => {
  const keys = [
    "厂商名",
    "厂商名 · 提交后按内置 OUI 表检索",
    "MAC 只能包含 0-9、A-F 以及 - : . 分隔符",
    "无法自动识别该查询格式；请选择完整 MAC、前缀、后缀或包含片段",
    "完整 MAC 需要 12 位十六进制字符",
    "前缀查询需要 6 位十六进制字符（OUI）",
    "后缀查询需要 4 位十六进制字符",
    "包含片段查询至少需要 2 位十六进制字符",
    "未收录该厂商；可改用 6 位 OUI 前缀查询",
    "该查询方式需要十六进制字符",
    "正在查询…",
    "虚拟网卡",
    "已关联设备档案",
    "批量查询最多 100 行。"
  ];
  for (const key of keys) {
    const value = i18n.t(key);
    assert.notEqual(value, key, key);
    assert.ok(!/[\u3400-\u9fff]/.test(value), key + " -> " + value);
  }
});

test("backend MAC lookup errors are localized without residual Chinese", () => {
  const messages = [
    "请输入完整的 MAC、前缀或后缀",
    "MAC 只能包含 0-9、A-F 以及 - : . 分隔符",
    "未收录该厂商；可改用 6 位 OUI 前缀查询",
    "该查询方式需要十六进制字符",
    "完整 MAC 需要 12 位十六进制字符",
    "前缀查询需要 6 位十六进制字符（OUI）",
    "后缀查询需要 4 位十六进制字符",
    "包含片段查询至少需要 2 位十六进制字符"
  ];
  for (const message of messages) {
    const value = i18n.translateMessage(message);
    assert.notEqual(value, message, message);
    assert.ok(!/[\u3400-\u9fff]/.test(value), value);
  }
});
