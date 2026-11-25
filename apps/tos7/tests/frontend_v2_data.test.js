"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

require("../frontend/csv.js");
require("../frontend/v2-data.js");
const data = globalThis.NetworkLocatorData;

test("macKind classifies full, prefix, suffix and fragment queries", () => {
  assert.equal(data.macKind("3C-07-54-9A-1B-2C").kind, "full");
  assert.equal(data.macKind("3C0754").kind, "prefix");
  assert.equal(data.macKind("1B2C").kind, "suffix");
  assert.equal(data.macKind("7549A1B").kind, "invalid");
  assert.equal(data.macKind("7549A1B", "any").kind, "any");
  assert.equal(data.macKind("Apple").kind, "vendor");
  assert.equal(data.macKind("AA:BB:GG").kind, "invalid");
  assert.equal(data.macKind("").kind, "empty");
  assert.equal(data.macKind("aa:bb:cc").compact, "AABBCC");
});

test("status labels and CSS classes are stable", () => {
  assert.equal(data.statusLabel("online"), "在线");
  assert.equal(data.statusLabel("offline"), "离线");
  assert.equal(data.statusLabel("unknown"), "未知");
  assert.equal(data.statusClass("online"), "v2-status v2-status--online");
  assert.equal(data.statusClass("bogus"), "v2-status v2-status--unknown");
});

test("device CSV uses backend CSV settings", () => {
  const text = data.buildDeviceCsv([
    {
      name: "会议室电视",
      ip: "192.0.2.44",
      mac: "3C-07-54-9A-1B-2C",
      vendor: "Apple",
      status: "online",
      interface: "eth0",
      network_id: "eth0|192.0.2.0/24",
      random_mac: false,
      first_seen: "2026-01-01T10:00:00",
      last_seen: "2026-01-01T11:00:00",
      note: "3F",
      favorite: true
    }
  ], { csv_delimiter: ";", csv_include_header: true, csv_bom: false });
  assert.ok(!text.startsWith("\ufeff"));
  assert.match(text, /^设备名称;IP 地址;MAC 地址;厂商;状态/);
  assert.match(text, /会议室电视;192\.0\.2\.44;3C-07-54-9A-1B-2C;Apple;在线/);
  assert.match(text, /;是$/);
});
