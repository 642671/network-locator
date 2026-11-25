/* Network Locator V2 — shared API client, formatting and DOM helpers. */
(function (root) {
  "use strict";

  function app() {
    return root.NetworkLocatorApp || null;
  }

  function tr(value) {
    if (root.NetworkLocatorI18n) {
      return root.NetworkLocatorI18n.t(String(value));
    }
    return String(value);
  }

  function translateMessage(value) {
    if (root.NetworkLocatorI18n && typeof root.NetworkLocatorI18n.translateMessage === "function") {
      return root.NetworkLocatorI18n.translateMessage(String(value || ""));
    }
    return String(value || "");
  }

  function countUnit(count, zhUnit, enOne, enMany) {
    var value = Number(count);
    if (!Number.isFinite(value)) {
      value = 0;
    }
    if (root.NetworkLocatorI18n && root.NetworkLocatorI18n.locale() === "en") {
      return value + " " + (value === 1 ? enOne : enMany);
    }
    return value + zhUnit;
  }

  function countDevices(count) {
    return countUnit(count, " 台设备", "device", "devices");
  }

  function countNetworks(count) {
    return countUnit(count, " 个网段", "network", "networks");
  }

  function countTasks(count) {
    return countUnit(count, " 个任务", "task", "tasks");
  }

  function deviceName(device) {
    if (!device) {
      return tr("未命名设备");
    }
    var name = String(device.name || "").trim();
    if (device.live) {
      name = translateMessage(name);
    }
    if (name && name !== "未命名设备") {
      return name;
    }
    return tr("未命名设备");
  }

  async function request(endpoint, payload, options) {
    var bridge = app();
    if (!bridge || typeof bridge.apiRequest !== "function") {
      throw new Error(tr("应用数据层未就绪"));
    }
    return bridge.apiRequest(endpoint, payload, options);
  }

  function toast(message, isError) {
    var bridge = app();
    if (bridge && typeof bridge.toast === "function") {
      bridge.toast(message, !!isError);
    }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function clear(node) {
    if (!node) {
      return;
    }
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) {
      node.textContent = String(value);
    }
  }

  function setHidden(id, hidden) {
    var node = typeof id === "string" ? document.getElementById(id) : id;
    if (node) {
      node.hidden = !!hidden;
    }
  }

  function parseDate(value) {
    if (value instanceof Date) {
      return value;
    }
    if (typeof value === "number") {
      return new Date(value);
    }
    var text = String(value || "").trim();
    if (!text) {
      return null;
    }
    var parsed = new Date(text);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatTime(value, relative) {
    var date = parseDate(value);
    if (!date) {
      return "--";
    }
    var now = new Date();
    var seconds = Math.max(0, (now.getTime() - date.getTime()) / 1000);
    if (relative) {
      if (seconds < 60) {
        return tr("刚刚");
      }
      if (seconds < 3600) {
        return Math.floor(seconds / 60) + tr(" 分钟前");
      }
      if (seconds < 86400) {
        return Math.floor(seconds / 3600) + tr(" 小时前");
      }
      if (seconds < 86400 * 30) {
        return Math.floor(seconds / 86400) + tr(" 天前");
      }
    }
    var time = pad(date.getHours()) + ":" + pad(date.getMinutes());
    if (date.toDateString() === now.toDateString()) {
      return time;
    }
    if (date.getFullYear() === now.getFullYear()) {
      return (date.getMonth() + 1) + "-" + pad(date.getDate()) + " " + time;
    }
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + " " + time;
  }

  function formatDuration(startValue, endValue) {
    var start = parseDate(startValue);
    var end = parseDate(endValue) || new Date();
    if (!start) {
      return "--";
    }
    var seconds = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000));
    if (seconds < 60) {
      return seconds + "s";
    }
    var minutes = Math.floor(seconds / 60);
    var rest = seconds % 60;
    if (minutes < 60) {
      return minutes + "m " + rest + "s";
    }
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }

  function formatBytes(value) {
    var size = Number(value) || 0;
    if (size < 1024) {
      return size + " B";
    }
    if (size < 1024 * 1024) {
      return (size / 1024).toFixed(1) + " KB";
    }
    return (size / 1024 / 1024).toFixed(2) + " MB";
  }

  var STATUS_LABELS = { online: "在线", offline: "离线", unknown: "未知" };
  var STATE_LABELS = {
    LOCAL: "本机",
    REACHABLE: "可达",
    DELAY: "延迟",
    STALE: "缓存",
    PROBE: "探测中"
  };
  var EVENT_LABELS = {
    discovered: "首次发现",
    ip_changed: "IP 变化",
    mac_changed: "MAC 变化",
    online: "重新上线",
    offline: "变为离线",
    renamed: "重命名",
    note: "备注更新",
    favorite: "收藏变更"
  };
  var KIND_LABELS = { mac: "MAC 定位", inventory: "设备扫描", network: "网络扫描", custom: "自定义范围" };

  function statusLabel(status) {
    return tr(STATUS_LABELS[status] || status || "未知");
  }

  function statusClass(status) {
    return "v2-status v2-status--" + (STATUS_LABELS[status] ? status : "unknown");
  }

  function stateLabel(value) {
    return tr(STATE_LABELS[value] || value || "");
  }

  function eventLabel(value) {
    return tr(EVENT_LABELS[value] || value || "");
  }

  function kindLabel(value) {
    return tr(KIND_LABELS[value] || value || "");
  }

  function statusBadge(status, reason) {
    var node = el("span", statusClass(status));
    node.appendChild(el("span", "v2-status-dot"));
    node.appendChild(document.createTextNode(statusLabel(status)));
    if (reason) {
      node.title = reason;
    }
    return node;
  }

  function statusReason(device) {
    if (!device) {
      return "";
    }
    var args = Array.isArray(device.status_reason_args) ? device.status_reason_args : [];
    switch (device.status_reason_code) {
      case "offline_not_found":
        return tr("最近一次完整扫描未发现该设备");
      case "neighbor_unconfirmed":
        return tr("邻居表中存在，但最近一次探测未确认可达");
      case "online_confirmed":
        return tr("最近一次扫描确认在线");
      case "never_checked":
        return tr("尚未检测");
      case "stale":
        return tr("超过 ") + (args[0] || 0) + tr(" 分钟未检测");
      case "preview_sample":
        return tr("预览示例数据");
      case "unknown":
        return tr("尚无明确结果");
      default:
        return translateMessage(device.status_reason || "");
    }
  }

  function eventDetail(event) {
    if (!event) {
      return "";
    }
    var args = Array.isArray(event.detail_args) ? event.detail_args : [];
    switch (event.detail_code) {
      case "discovered":
        return (args[0] || "") + (args[1] ? " · " + args[1] : "");
      case "ip_changed":
        return (args[0] || "") + " → " + (args[1] || "");
      case "mac_changed":
        return (args[0] || "") + " → " + (args[1] || "");
      case "online":
        return args[0] || "";
      case "offline":
        return "";
      case "renamed":
        return args[0] || "";
      case "renamed_cleared":
        return "";
      case "note":
        return "";
      case "favorite_added":
        return "";
      case "favorite_removed":
        return "";
      case "profile_updated":
        return "";
      default:
        return translateMessage(event.detail || "");
    }
  }

  function copy(text, label) {
    var value = String(text || "");
    if (!value) {
      return;
    }
    var bridge = app();
    var promise;
    if (bridge && typeof bridge.writeClipboard === "function") {
      promise = bridge.writeClipboard(value);
    } else if (navigator.clipboard && navigator.clipboard.writeText) {
      promise = navigator.clipboard.writeText(value);
    } else {
      promise = Promise.reject(new Error("clipboard unavailable"));
    }
    Promise.resolve(promise).then(function () {
      toast(tr("已复制") + (label ? " " + label : "") + "：" + value, false);
    }).catch(function () {
      toast(tr("复制失败，请手动选择文本。"), true);
    });
  }

  function downloadCsv(filename, content) {
    var blob = new Blob([content], { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function csvSettings(settings) {
    var value = settings || {};
    return {
      delimiter: value.csv_delimiter || ",",
      includeHeader: value.csv_include_header !== false,
      bom: value.csv_bom !== false
    };
  }

  function buildDeviceCsv(devices, settings) {
    var csv = root.LanMacCsv;
    if (!csv) {
      throw new Error("CSV 模块未加载");
    }
    var columns = [
      { label: tr("设备名称"), value: function (item) { return deviceName(item); } },
      { label: tr("IP 地址"), value: "ip" },
      { label: tr("MAC 地址"), value: "mac" },
      { label: tr("厂商"), value: function (item) { return item.vendor || tr("未知厂商"); } },
      { label: tr("状态"), value: function (item) { return statusLabel(item.status); } },
      { label: tr("网卡"), value: "interface" },
      { label: tr("网段"), value: "network_id" },
      { label: tr("随机 MAC"), value: function (item) { return item.random_mac ? tr("是") : tr("否"); } },
      { label: tr("首次发现"), value: "first_seen" },
      { label: tr("最近发现"), value: "last_seen" },
      { label: tr("备注"), value: "note" },
      { label: tr("收藏"), value: function (item) { return item.favorite ? tr("是") : tr("否"); } }
    ];
    return csv.buildCsv(devices || [], columns, csvSettings(settings));
  }

  function exportDevices(devices, settings, prefix) {
    var csv = root.LanMacCsv;
    var stamp = csv ? csv.dateStamp(new Date()) : String(Date.now());
    downloadCsv((prefix || "network-locator-devices") + "-" + stamp + ".csv", buildDeviceCsv(devices, settings));
  }

  function buildResultCsv(results, settings) {
    var csv = root.LanMacCsv;
    if (!csv) {
      throw new Error("CSV 模块未加载");
    }
    var columns = [
      { label: tr("网卡"), value: "interface" },
      { label: tr("扫描范围"), value: "scan_range" },
      { label: tr("IP 地址"), value: "ip" },
      { label: tr("MAC 地址"), value: "mac" },
      { label: tr("状态"), value: function (item) { return stateLabel(item.state) || item.state; } }
    ];
    return csv.buildCsv(results || [], columns, csvSettings(settings));
  }

  function exportResults(results, settings, prefix) {
    var csv = root.LanMacCsv;
    var stamp = csv ? csv.dateStamp(new Date()) : String(Date.now());
    downloadCsv((prefix || "network-locator-scan") + "-" + stamp + ".csv", buildResultCsv(results, settings));
  }

  function macKind(value) {
    var compact = String(value || "").toUpperCase().replace(/[^0-9A-F]/g, "");
    if (!compact) {
      return { kind: "empty", compact: "" };
    }
    if (compact.length === 12) {
      return { kind: "full", compact: compact };
    }
    if (compact.length === 6) {
      return { kind: "prefix", compact: compact };
    }
    if (compact.length <= 4) {
      return { kind: "suffix", compact: compact };
    }
    return { kind: "any", compact: compact };
  }

  function emptyState(container, message, kind) {
    clear(container);
    if (!container) {
      return;
    }
    var box = el("div", "v2-empty-state" + (kind ? " is-" + kind : ""));
    box.appendChild(el("strong", "", message || "暂无数据"));
    container.appendChild(box);
  }

  function loading(container, message) {
    clear(container);
    if (!container) {
      return;
    }
    var box = el("div", "v2-loading");
    box.appendChild(el("span", "v2-spinner"));
    box.appendChild(document.createTextNode(message || tr("正在加载…")));
    container.appendChild(box);
  }

  var API = {
    summary: function () { return request("v2/summary"); },
    networks: function () { return request("v2/networks"); },
    scanStatus: function () { return request("v2/scan/status"); },
    scanStart: function (body) { return request("v2/scan/start", body || {}); },
    scanPause: function () { return request("v2/scan/pause", {}); },
    scanResume: function () { return request("v2/scan/resume", {}); },
    scanStop: function () { return request("v2/scan/stop", {}); },
    devices: function (params) {
      var query = [];
      Object.keys(params || {}).forEach(function (key) {
        var value = params[key];
        if (value === undefined || value === null || value === "") {
          return;
        }
        query.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
      });
      return request("v2/devices" + (query.length ? "?" + query.join("&") : ""));
    },
    device: function (id) { return request("v2/devices/" + encodeURIComponent(id)); },
    updateDevice: function (id, patch) {
      return request("v2/devices/" + encodeURIComponent(id), patch, { method: "PATCH" });
    },
    inventoryScan: function (body) {
      return request("v2/devices/scan", body || {}, { timeoutMs: 180000 });
    },
    macLookup: function (query, mode) {
      return request(
        "v2/mac/lookup?q=" + encodeURIComponent(query) + "&mode=" + encodeURIComponent(mode || "auto")
      );
    },
    macBatch: function (queries) {
      return request("v2/mac/lookup", { queries: queries });
    },
    analysis: function () { return request("v2/analysis"); },
    ping: function (body) {
      return request("v2/analysis/ping", body, { timeoutMs: 60000 });
    },
    scans: function (limit) { return request("v2/scans?limit=" + encodeURIComponent(limit || 100)); },
    scan: function (id) { return request("v2/scans/" + encodeURIComponent(id)); },
    purgeScans: function (days) {
      return request("v2/scans/purge", days === undefined ? {} : { older_than_days: days });
    },
    settings: function () { return request("v2/settings"); },
    updateSettings: function (patch) {
      return request("v2/settings", patch, { method: "PATCH" });
    }
  };

  root.NetworkLocatorData = {
    API: API,
    request: request,
    toast: toast,
    tr: tr,
    translateMessage: translateMessage,
    el: el,
    clear: clear,
    setText: setText,
    setHidden: setHidden,
    formatTime: formatTime,
    formatDuration: formatDuration,
    formatBytes: formatBytes,
    countUnit: countUnit,
    countDevices: countDevices,
    countNetworks: countNetworks,
    countTasks: countTasks,
    deviceName: deviceName,
    statusLabel: statusLabel,
    statusClass: statusClass,
    statusBadge: statusBadge,
    statusReason: statusReason,
    stateLabel: stateLabel,
    eventLabel: eventLabel,
    eventDetail: eventDetail,
    kindLabel: kindLabel,
    copy: copy,
    downloadCsv: downloadCsv,
    exportDevices: exportDevices,
    exportResults: exportResults,
    buildDeviceCsv: buildDeviceCsv,
    buildResultCsv: buildResultCsv,
    macKind: macKind,
    emptyState: emptyState,
    loading: loading,
    csvSettings: csvSettings
  };
}(typeof window !== "undefined" ? window : globalThis));
