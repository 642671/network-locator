"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const EN = {
  "未命名设备": "Unnamed device",
  "未知厂商": "Unknown vendor",
  "最近一次完整扫描未发现该设备": "The latest complete scan did not find this device",
  "邻居表中存在，但最近一次探测未确认可达": "Present in the neighbor table, but the latest probe did not confirm reachability",
  "最近一次扫描确认在线": "Confirmed online by the latest scan",
  "尚未检测": "Not checked yet",
  "超过 ": "More than ",
  " 分钟未检测": " minutes since the last check",
  "尚无明确结果": "No definitive result yet",
  "预览示例数据": "Preview sample data",
  "IP 变化": "IP changed",
  "MAC 变化": "MAC changed",
  " 重新上线": " came back online",
  "完整扫描中未发现": "Not found in the complete scan",
  "重命名为 ": "Renamed to ",
  "已清空名称": "Name cleared",
  "备注已更新": "Note updated",
  "已收藏": "Favorited",
  "已取消收藏": "Unfavorited",
  "设备档案已更新": "Device profile updated",
  "首次发现": "First seen",
  "设备名称": "Device name",
  "IP 地址": "IP address",
  "MAC 地址": "MAC address",
  "厂商": "Vendor",
  "状态": "Status",
  "网卡": "Interface",
  "网段": "Network",
  "随机 MAC": "Random MAC",
  "最近发现": "Last seen",
  "备注": "Note",
  "收藏": "Favorite",
  "是": "Yes",
  "否": "No",
  "在线": "Online",
  "离线": "Offline",
  "未知": "Unknown"
};

globalThis.NetworkLocatorI18n = {
  locale: () => "en",
  t: (key) => EN[key] || key,
  translateMessage: (value) => value
};

require("../frontend/csv.js");
require("../frontend/v2-data.js");
const data = globalThis.NetworkLocatorData;

test("device names fall back to English only for the placeholder", () => {
  assert.equal(data.deviceName({ name: "未命名设备" }), "Unnamed device");
  assert.equal(data.deviceName({ name: "Apple 1B2C" }), "Apple 1B2C");
  assert.equal(data.deviceName({ display_name: "Owner TV", name: "Owner TV" }), "Owner TV");
});

test("status reason codes render English instead of backend Chinese", () => {
  assert.equal(
    data.statusReason({ status_reason_code: "stale", status_reason_args: [30] }),
    "More than 30 minutes since the last check"
  );
  assert.equal(
    data.statusReason({ status_reason_code: "offline_not_found" }),
    "The latest complete scan did not find this device"
  );
  assert.equal(data.statusReason({ status_reason_code: "preview_sample" }), "Preview sample data");
});

test("event detail codes render English with their arguments", () => {
  assert.equal(
    data.eventDetail({ detail_code: "ip_changed", detail_args: ["192.0.2.80", "192.0.2.88"] }),
    "192.0.2.80 → 192.0.2.88"
  );
  assert.equal(
    data.eventDetail({ detail_code: "discovered", detail_args: ["192.0.2.44", "3C-07-54-9A-1B-2C"] }),
    "192.0.2.44 · 3C-07-54-9A-1B-2C"
  );
  assert.equal(data.eventDetail({ detail_code: "renamed", detail_args: ["Living room TV"] }), "Living room TV");
});

test("CSV headers and fallback values are English", () => {
  const text = data.buildDeviceCsv(
    [
      {
        name: "未命名设备",
        ip: "192.0.2.44",
        mac: "3C-07-54-9A-1B-2C",
        vendor: "",
        status: "online",
        random_mac: false,
        favorite: false
      }
    ],
    { csv_delimiter: ",", csv_include_header: true, csv_bom: false }
  );
  assert.match(text, /^Device name,IP address,MAC address,Vendor,Status/);
  assert.match(text, /Unnamed device,192\.0\.2\.44,3C-07-54-9A-1B-2C,Unknown vendor,Online/);
  assert.match(text, /,No,,,,No$/);
});
