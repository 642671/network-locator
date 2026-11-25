/* Network Locator V2 — page controllers for dashboard, inventory, MAC lookup,
   analysis, history, settings and the device detail drawer. */
(function (root) {
  "use strict";

  var D = root.NetworkLocatorData;

  function doc(id) {
    return document.getElementById(id);
  }

  var state = {
    route: "",
    summary: null,
    dashboard: {
      list: [],
      query: "",
      status: "",
      sort: "last_seen",
      offset: 0,
      limit: 50,
      token: 0
    },
    inventory: {
      list: [],
      query: "",
      status: "",
      favorite: false,
      sort: "last_seen",
      direction: "desc",
      selected: {},
      total: 0,
      offset: 0,
      limit: 50,
      stats: null,
      settings: null,
      token: 0
    },
    mac: {
      last: null,
      batch: false
    },
    analysis: null,
    history: {
      tasks: [],
      detail: null
    },
    settings: null,
    drawer: {
      device: null,
      saving: false,
      token: 0,
      currentId: ""
    },
    autoScanRunning: false,
    autoScanTimer: null
  };

  function currentRoute() {
    var value = String(root.location.hash || "").replace(/^#\/?/, "");
    return value || "dashboard";
  }

  function debounce(fn, delay) {
    var timer = null;
    return function () {
      var args = arguments;
      var context = this;
      root.clearTimeout(timer);
      timer = root.setTimeout(function () {
        fn.apply(context, args);
      }, delay);
    };
  }

  function setBusy(button, busy, label) {
    if (!button) {
      return;
    }
    if (busy) {
      if (!button.getAttribute("data-label")) {
        button.setAttribute("data-label", button.textContent);
      }
      button.disabled = true;
      button.textContent = label || D.tr("处理中…");
    } else {
      button.disabled = false;
      if (button.getAttribute("data-label")) {
        button.textContent = button.getAttribute("data-label");
        button.removeAttribute("data-label");
      }
    }
  }

  function paintPager(prefix, offset, count, total) {
    var pager = doc(prefix + "Pager");
    var info = doc(prefix + "PagerInfo");
    var prev = doc(prefix + "Prev");
    var next = doc(prefix + "Next");
    if (info) {
      var page = Math.floor(offset / Math.max(1, state.inventory.limit)) + 1;
      if (prefix === "v2Dash") {
        page = Math.floor(offset / Math.max(1, state.dashboard.limit)) + 1;
      }
      var start = total ? offset + 1 : 0;
      var end = offset + count;
      info.textContent = D.tr("第") + " " + page + D.tr(" 页") + " · " + start + "–" + end + " / " + total;
    }
    if (prev) {
      prev.disabled = offset <= 0;
    }
    if (next) {
      next.disabled = offset + count >= total;
    }
    if (pager) {
      pager.hidden = total === 0 || (total <= count && offset === 0);
    }
  }

  async function fetchAllDevices(params) {
    var collected = [];
    var total = 0;
    var settings = null;
    var offset = 0;
    var guard = 0;
    do {
      var page = Object.assign({}, params || {}, { limit: 1000, offset: offset });
      var payload = await D.API.devices(page);
      var devices = payload.devices || [];
      settings = payload.settings || settings;
      total = payload.total || 0;
      collected = collected.concat(devices);
      offset += devices.length;
      guard += 1;
      if (!devices.length || offset >= total || guard > 500) {
        break;
      }
    } while (true);
    return { devices: collected, total: total, settings: settings };
  }

  function openDevice(deviceId) {
    if (!deviceId) {
      return;
    }
    var shell = root.NetworkLocatorShell;
    if (shell && typeof shell.openDrawer === "function") {
      shell.openDrawer();
    } else {
      var drawer = doc("v2Drawer");
      if (drawer) {
        drawer.hidden = false;
      }
    }
    loadDrawer(deviceId);
  }

  function closeDevice() {
    var shell = root.NetworkLocatorShell;
    if (shell && typeof shell.closeDrawer === "function") {
      shell.closeDrawer();
    } else {
      var drawer = doc("v2Drawer");
      if (drawer) {
        drawer.hidden = true;
      }
    }
  }

  function appSettings() {
    return state.inventory.settings || (state.settings && state.settings.settings) || {};
  }

  function exportButtonLabel(count) {
    return count ? D.tr("导出 ") + D.countDevices(count) : D.tr("导出 CSV");
  }

  function makeCopyButton(text, label) {
    var button = D.el("button", "v2-icon-button v2-icon-button-sm", label || "复制");
    button.type = "button";
    button.title = D.tr("复制") + " " + (label || "");
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      D.copy(text, label);
    });
    return button;
  }

  function makeDetailButton(device) {
    var button = D.el("button", "v2-text-button", D.tr("详情"));
    button.type = "button";
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      openDevice(device.device_id);
    });
    return button;
  }

  function makeFavoriteButton(device) {
    var button = D.el(
      "button",
      "v2-icon-button v2-icon-button-sm" + (device.favorite ? " is-favorite" : ""),
      device.favorite ? "★" : "☆"
    );
    button.type = "button";
    button.title = device.favorite ? D.tr("取消收藏") : D.tr("收藏");
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      button.disabled = true;
      D.API.updateDevice(device.device_id, { favorite: !device.favorite })
        .then(function () {
          D.toast(device.favorite ? D.tr("已取消收藏") : D.tr("已收藏"), false);
          refreshCurrent();
        })
        .catch(function (error) {
          D.toast(error.message || D.tr("操作失败"), true);
          button.disabled = false;
        });
    });
    return button;
  }

  function deviceRow(device, options) {
    var opts = options || {};
    var tr = D.el("tr", "v2-device-row");
    tr.setAttribute("data-device-id", device.device_id || "");

    if (opts.selectable) {
      var checkCell = D.el("td", "v2-check-col");
      var checkbox = D.el("input");
      checkbox.type = "checkbox";
      checkbox.checked = !!(device.device_id && state.inventory.selected[device.device_id]);
      checkbox.setAttribute("aria-label", D.tr("选择") + " " + D.deviceName(device));
      checkbox.addEventListener("click", function (event) {
        event.stopPropagation();
      });
      checkbox.addEventListener("change", function () {
        if (!device.device_id) {
          return;
        }
        if (checkbox.checked) {
          state.inventory.selected[device.device_id] = device;
        } else {
          delete state.inventory.selected[device.device_id];
        }
        updateBulkBar();
      });
      checkCell.appendChild(checkbox);
      tr.appendChild(checkCell);
    }

    var nameCell = D.el("td");
    var nameLine = D.el("div", "v2-name-line");
    var nameNode = D.el("strong", "", D.deviceName(device));
    nameNode.title = D.deviceName(device);
    nameLine.appendChild(nameNode);
    if (device.favorite) {
      nameLine.appendChild(D.el("span", "v2-fav", "★"));
    }
    if (device.random_mac) {
      nameLine.appendChild(D.el("span", "v2-mini-badge", D.tr("随机 MAC")));
    }
    nameCell.appendChild(nameLine);
    nameCell.appendChild(D.el("span", "v2-subtle", device.mac || "--"));
    tr.appendChild(nameCell);

    var ipCell = D.el("td");
    var ipLine = D.el("div", "v2-copy-line");
    ipLine.appendChild(D.el("code", "", device.ip || "--"));
    if (device.ip) {
      ipLine.appendChild(makeCopyButton(device.ip, "IP"));
    }
    ipCell.appendChild(ipLine);
    tr.appendChild(ipCell);

    var macCell = D.el("td");
    var macLine = D.el("div", "v2-copy-line");
    macLine.appendChild(D.el("code", "", device.mac || "--"));
    if (device.mac) {
      macLine.appendChild(makeCopyButton(device.mac, "MAC"));
    }
    macCell.appendChild(macLine);
    tr.appendChild(macCell);

    var vendorCell = D.el("td");
    vendorCell.appendChild(
      D.el("span", device.vendor ? "" : "v2-muted", vendorText(device.vendor))
    );
    tr.appendChild(vendorCell);

    var statusCell = D.el("td");
    statusCell.appendChild(D.statusBadge(device.status, D.statusReason(device)));
    tr.appendChild(statusCell);

    if (opts.showNetwork !== false) {
      var networkCell = D.el("td");
      var networkLabel = device.network_id
        ? String(device.network_id).split("|").pop()
        : (device.interface || "--");
      var networkNode = D.el("span", "v2-subtle", networkLabel);
      networkNode.title = device.network_id || networkLabel;
      networkCell.appendChild(networkNode);
      tr.appendChild(networkCell);
    }

    var seenCell = D.el("td");
    var seen = D.el("span", "", D.formatTime(device.last_seen, true));
    seen.title = D.formatTime(device.last_seen, false);
    seenCell.appendChild(seen);
    tr.appendChild(seenCell);

    var actionsCell = D.el("td", "v2-actions-cell");
    actionsCell.appendChild(makeDetailButton(device));
    actionsCell.appendChild(makeFavoriteButton(device));
    tr.appendChild(actionsCell);

    tr.addEventListener("click", function (event) {
      if (event.target && event.target.closest && event.target.closest("button, input, a")) {
        return;
      }
      if (device.device_id) {
        openDevice(device.device_id);
      }
    });
    return tr;
  }

  function renderDeviceTable(tbody, devices, options) {
    D.clear(tbody);
    devices.forEach(function (device) {
      tbody.appendChild(deviceRow(device, options));
    });
  }

  async function loadDashboard() {
    var token = ++state.dashboard.token;
    var loading = doc("v2DashLoading");
    var empty = doc("v2DashEmpty");
    if (loading) {
      loading.hidden = false;
    }
    if (empty) {
      empty.hidden = true;
    }
    try {
      var results = await Promise.all([
        D.API.summary(),
        D.API.devices({
          query: state.dashboard.query,
          status: state.dashboard.status,
          sort: state.dashboard.sort,
          direction: "desc",
          limit: state.dashboard.limit,
          offset: state.dashboard.offset
        })
      ]);
      if (token !== state.dashboard.token) {
        return;
      }
      state.summary = results[0];
      state.settings = results[0].settings || state.settings;
      renderDashboard(results[0], results[1]);
    } catch (error) {
      if (loading) {
        loading.hidden = true;
      }
      D.toast(error.message || D.tr("设备总览加载失败"), true);
      var tbody = doc("v2DashTableBody");
      if (tbody) {
        D.clear(tbody);
      }
      if (empty) {
        empty.hidden = false;
        empty.textContent = error.message || D.tr("设备总览加载失败，请检查服务是否在线。");
      }
      if (doc("v2DashUpdated")) {
        doc("v2DashUpdated").textContent = D.tr("加载失败");
      }
    }
  }

  function renderDashboard(summary, devicesPayload) {
    var stats = summary.stats || {};
    var warnings = summary.warnings || [];
    var warningBox = doc("v2DashWarnings");
    if (warningBox) {
      warningBox.hidden = warnings.length === 0;
      warningBox.textContent = warnings.map(function (item) { return D.tr(item); }).join(D.tr("；"));
    }
    D.setText("v2StatDevices", stats.total || 0);
    D.setText("v2StatOnline", stats.online || 0);
    D.setText("v2StatOffline", (stats.offline || 0) + (stats.unknown || 0));
    D.setText("v2StatNetworks", (summary.networks || []).length || stats.networks || 0);
    D.setText("v2StatSaved", stats.favorites || 0);
    D.setText("v2StatScans", stats.scans_today || 0);
    D.setText("v2DashDeviceCount", devicesPayload.total || devicesPayload.devices.length);
    D.setText(
      "v2DashUpdated",
      D.tr("更新于 ") + D.formatTime(new Date(), false) +
        (stats.last_scan_at ? " · " + D.tr("上次扫描 ") + D.formatTime(stats.last_scan_at, true) : "")
    );

    var networkList = doc("v2NetworkList");
    var networkEmpty = doc("v2NetworkEmpty");
    D.clear(networkList);
    var networks = summary.networks || [];
    if (networkEmpty) {
      networkEmpty.hidden = networks.length > 0;
    }
    networks.forEach(function (network) {
      var row = D.el("div", "v2-list-row");
      var main = D.el("div", "v2-list-main");
      main.appendChild(D.el("strong", "", network.interface + " · " + network.scan_range));
      main.appendChild(
        D.el(
          "span",
          "v2-subtle",
          network.local_ip + "/" + network.prefix_length +
            (network.gateway ? D.tr(" · 网关 ") + network.gateway : D.tr(" · 无默认网关"))
        )
      );
      row.appendChild(main);
      row.appendChild(D.el("span", "v2-count", network.device_count || 0));
      networkList.appendChild(row);
    });

    var recentList = doc("v2RecentList");
    var recentEmpty = doc("v2RecentEmpty");
    D.clear(recentList);
    var recent = summary.recent || [];
    if (recentEmpty) {
      recentEmpty.hidden = recent.length > 0;
    }
    recent.forEach(function (device) {
      var row = D.el("div", "v2-list-row v2-list-row--clickable");
      var main = D.el("div", "v2-list-main");
      var line = D.el("div", "v2-name-line");
      line.appendChild(D.el("strong", "", D.deviceName(device)));
      line.appendChild(D.statusBadge(device.status, D.statusReason(device)));
      main.appendChild(line);
      main.appendChild(D.el("span", "v2-subtle", device.ip + " · " + device.mac));
      row.appendChild(main);
      row.appendChild(D.el("span", "v2-subtle", D.formatTime(device.last_seen, true)));
      row.addEventListener("click", function () {
        openDevice(device.device_id);
      });
      recentList.appendChild(row);
    });

    var tbody = doc("v2DashTableBody");
    var empty = doc("v2DashEmpty");
    var loading = doc("v2DashLoading");
    if (loading) {
      loading.hidden = true;
    }
    var list = devicesPayload.devices || [];
    if (!list.length && (devicesPayload.total || 0) > 0 && state.dashboard.offset > 0) {
      state.dashboard.offset = 0;
      return loadDashboard();
    }
    if (empty) {
      empty.hidden = list.length > 0;
    }
    renderDeviceTable(tbody, list, { showNetwork: false });
    paintPager("v2Dash", state.dashboard.offset, list.length, devicesPayload.total || list.length);
  }

  function bindDashboard() {
    var refresh = doc("v2DashRefresh");
    if (refresh) {
      refresh.addEventListener("click", function () {
        loadDashboard();
      });
    }
    var search = doc("v2DashSearch");
    if (search) {
      search.addEventListener("input", debounce(function () {
        state.dashboard.query = search.value.trim();
        state.dashboard.offset = 0;
        loadDashboard();
      }, 260));
    }
    var status = doc("v2DashStatus");
    if (status) {
      status.addEventListener("change", function () {
        state.dashboard.status = status.value;
        state.dashboard.offset = 0;
        loadDashboard();
      });
    }
    var sort = doc("v2DashSort");
    if (sort) {
      sort.addEventListener("change", function () {
        state.dashboard.sort = sort.value;
        state.dashboard.offset = 0;
        loadDashboard();
      });
    }
    var exportButton = doc("v2Export");
    if (exportButton) {
      exportButton.addEventListener("click", exportDashboard);
    }
    var prev = doc("v2DashPrev");
    if (prev) {
      prev.addEventListener("click", function () {
        state.dashboard.offset = Math.max(0, state.dashboard.offset - state.dashboard.limit);
        loadDashboard();
      });
    }
    var next = doc("v2DashNext");
    if (next) {
      next.addEventListener("click", function () {
        state.dashboard.offset += state.dashboard.limit;
        loadDashboard();
      });
    }
  }

  async function exportDashboard() {
    try {
      var payload = await fetchAllDevices({
        query: state.dashboard.query,
        status: state.dashboard.status,
        sort: state.dashboard.sort,
        direction: "desc"
      });
      D.exportDevices(payload.devices || [], payload.settings || appSettings(), "network-locator-dashboard");
      D.toast(D.tr("已导出 ") + D.countDevices((payload.devices || []).length), false);
    } catch (error) {
      D.toast(error.message || D.tr("导出失败"), true);
    }
  }  function refreshCurrent() {
    var route = state.route || currentRoute();
    if (route === "dashboard") {
      return loadDashboard();
    }
    if (route === "inventory") {
      return loadInventory();
    }
    if (route === "analysis") {
      return loadAnalysis();
    }
    if (route === "history") {
      return loadHistory();
    }
    if (route === "settings") {
      return loadSettings();
    }
    return Promise.resolve();
  }

  /* ---------------------------------------------------------------- inventory */

  function inventoryParams(limit, offset) {
    var inv = state.inventory;
    return {
      query: inv.query,
      status: inv.status,
      favorite: inv.favorite ? 1 : "",
      sort: inv.sort,
      direction: inv.direction,
      limit: limit || inv.limit,
      offset: offset === undefined ? inv.offset : offset
    };
  }

  async function loadInventory() {
    var token = ++state.inventory.token;
    var loading = doc("v2InvLoading");
    var empty = doc("v2InvEmpty");
    if (loading) {
      loading.hidden = false;
    }
    if (empty) {
      empty.hidden = true;
    }
    try {
      var payload = await D.API.devices(inventoryParams());
      if (token !== state.inventory.token) {
        return;
      }
      state.inventory.list = payload.devices || [];
      state.inventory.total = payload.total || 0;
      state.inventory.stats = payload.stats || {};
      state.inventory.settings = payload.settings || null;
      renderInventory(payload);
    } catch (error) {
      if (token !== state.inventory.token) {
        return;
      }
      state.inventory.list = [];
      var tbody = doc("v2InvTableBody");
      if (tbody) {
        D.clear(tbody);
      }
      if (empty) {
        empty.hidden = false;
        empty.textContent = error.message || D.tr("设备列表加载失败，请检查服务是否在线。");
      }
      D.setText("v2InvSummary", D.tr("加载失败"));
      D.toast(error.message || D.tr("设备列表加载失败"), true);
    } finally {
      if (token === state.inventory.token && loading) {
        loading.hidden = true;
      }
    }
  }

  function selectedIds() {
    return Object.keys(state.inventory.selected);
  }

  function syncSelectAll() {
    var all = doc("v2InvSelectAll");
    if (!all) {
      return;
    }
    var list = state.inventory.list || [];
    var selected = list.filter(function (device) {
      return device.device_id && state.inventory.selected[device.device_id];
    }).length;
    all.checked = list.length > 0 && selected === list.length;
    all.indeterminate = selected > 0 && selected < list.length;
  }

  function updateBulkBar() {
    var count = selectedIds().length;
    var bar = doc("v2InvBulk");
    if (bar) {
      bar.hidden = count === 0;
    }
    D.setText("v2InvBulkText", D.tr("已选 ") + D.countDevices(count));
    var exportButton = doc("v2InvBulkExport");
    if (exportButton) {
      exportButton.disabled = count === 0;
    }
    var favoriteButton = doc("v2InvBulkFavorite");
    if (favoriteButton) {
      favoriteButton.disabled = count === 0;
    }
    syncSelectAll();
  }

  function renderInventory(payload) {
    var stats = payload.stats || state.inventory.stats || {};
    D.setText("v2InvCountAll", stats.total || 0);
    D.setText("v2InvCountOnline", stats.online || 0);
    D.setText("v2InvCountOffline", stats.offline || 0);
    D.setText("v2InvCountUnknown", stats.unknown || 0);
    D.setText("v2InvCountFavorite", stats.favorites || 0);
    D.setText(
      "v2InvSummary",
      D.tr("共 ") + D.countDevices(stats.total || 0) +
        " · " + D.tr("在线 ") + (stats.online || 0) +
        " · " + D.tr("离线 ") + (stats.offline || 0) +
        " · " + D.tr("未知 ") + (stats.unknown || 0) +
        " · " + D.tr("收藏 ") + (stats.favorites || 0)
    );
    var list = payload.devices || [];
    if (!list.length && (payload.total || 0) > 0 && state.inventory.offset > 0) {
      state.inventory.offset = 0;
      return loadInventory();
    }
    (payload.devices || []).forEach(function (device) {
      if (device.device_id && state.inventory.selected[device.device_id]) {
        state.inventory.selected[device.device_id] = device;
      }
    });
    var tbody = doc("v2InvTableBody");
    if (tbody) {
      renderDeviceTable(tbody, list, { selectable: true });
    }
    var empty = doc("v2InvEmpty");
    if (empty) {
      empty.hidden = list.length > 0;
      empty.textContent = D.tr("没有匹配的设备。");
    }
    updateBulkBar();
    paintPager("v2Inv", state.inventory.offset, list.length, payload.total || list.length);
  }

  function setInventoryFilter(status, favorite) {
    state.inventory.status = status || "";
    state.inventory.favorite = !!favorite;
    state.inventory.offset = 0;
    var filters = doc("v2InvFilters");
    if (filters) {
      var buttons = filters.querySelectorAll("button");
      for (var index = 0; index < buttons.length; index += 1) {
        var button = buttons[index];
        var isStatus = button.hasAttribute("data-status-filter");
        var isFavorite = button.hasAttribute("data-favorite-filter");
        var active = isStatus
          ? button.getAttribute("data-status-filter") === state.inventory.status && !state.inventory.favorite
          : isFavorite
            ? state.inventory.favorite
            : false;
        button.classList.toggle("is-active", active);
      }
    }
    loadInventory();
  }

  async function exportInventory(selectedOnly) {
    try {
      if (selectedOnly) {
        var chosen = Object.keys(state.inventory.selected).map(function (id) {
          return state.inventory.selected[id];
        }).filter(function (device) {
          return device && device.device_id;
        });
        D.exportDevices(chosen, appSettings(), "network-locator-selected");
        D.toast(D.tr("已导出 ") + D.countDevices(chosen.length), false);
        return;
      }
      var payload = await fetchAllDevices(inventoryParams(undefined, 0));
      D.exportDevices(payload.devices || [], payload.settings || appSettings(), "network-locator-inventory");
      D.toast(D.tr("已导出 ") + D.countDevices((payload.devices || []).length), false);
    } catch (error) {
      D.toast(error.message || D.tr("导出失败"), true);
    }
  }

  async function favoriteSelected() {
    var ids = selectedIds();
    if (!ids.length) {
      return;
    }
    var button = doc("v2InvBulkFavorite");
    setBusy(button, true, D.tr("处理中…"));
    try {
      await Promise.all(ids.map(function (id) {
        return D.API.updateDevice(id, { favorite: true });
      }));
      D.toast(D.tr("已收藏 ") + D.countDevices(ids.length), false);
      await loadInventory();
    } catch (error) {
      D.toast(error.message || D.tr("批量收藏失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  async function runInventoryScan(triggerButton) {
    var button = triggerButton && triggerButton.tagName ? triggerButton : doc("v2InvScan");
    setBusy(button, true, D.tr("扫描中…"));
    D.toast(D.tr("开始扫描当前网段的在线设备，请稍候。"), false);
    try {
      var payload = await D.API.inventoryScan({});
      var task = payload.task || {};
      D.toast(
        D.tr("扫描完成：发现 ") + (task.discovered || (payload.devices || []).length) +
          D.tr(" 台，新增 ") + (task.new_devices || 0) +
          D.tr(" 台，IP 变化 ") + (task.ip_changes || 0) + D.tr(" 台"),
        false
      );
      if (state.route === "dashboard") {
        await loadDashboard();
      } else {
        await loadInventory();
      }
    } catch (error) {
      D.toast(error.message || D.tr("扫描失败，未生成扫描结果。"), true);
    } finally {
      setBusy(button, false);
    }
  }

  function bindInventory() {
    var filters = doc("v2InvFilters");
    if (filters) {
      filters.addEventListener("click", function (event) {
        var button = event.target.closest("button");
        if (!button) {
          return;
        }
        if (button.hasAttribute("data-favorite-filter")) {
          setInventoryFilter("", true);
        } else if (button.hasAttribute("data-status-filter")) {
          setInventoryFilter(button.getAttribute("data-status-filter"), false);
        }
      });
    }
    var search = doc("v2InvSearch");
    if (search) {
      search.addEventListener("input", debounce(function () {
        state.inventory.query = search.value.trim();
        state.inventory.offset = 0;
        loadInventory();
      }, 260));
    }
    var sort = doc("v2InvSort");
    if (sort) {
      sort.addEventListener("change", function () {
        state.inventory.sort = sort.value;
        state.inventory.offset = 0;
        loadInventory();
      });
    }
    var direction = doc("v2InvDirection");
    if (direction) {
      direction.addEventListener("change", function () {
        state.inventory.direction = direction.value;
        state.inventory.offset = 0;
        loadInventory();
      });
    }
    var clear = doc("v2InvClear");
    if (clear) {
      clear.addEventListener("click", function () {
        state.inventory.query = "";
        state.inventory.sort = "last_seen";
        state.inventory.direction = "desc";
        if (search) {
          search.value = "";
        }
        if (sort) {
          sort.value = "last_seen";
        }
        if (direction) {
          direction.value = "desc";
        }
        state.inventory.selected = {};
        state.inventory.offset = 0;
        setInventoryFilter("", false);
      });
    }
    var selectAll = doc("v2InvSelectAll");
    if (selectAll) {
      selectAll.addEventListener("change", function () {
        var list = state.inventory.list || [];
        list.forEach(function (device) {
          if (!device.device_id) {
            return;
          }
          if (selectAll.checked) {
            state.inventory.selected[device.device_id] = device;
          } else {
            delete state.inventory.selected[device.device_id];
          }
        });
        renderDeviceTable(doc("v2InvTableBody"), list, { selectable: true });
        updateBulkBar();
      });
    }
    var bulkFavorite = doc("v2InvBulkFavorite");
    if (bulkFavorite) {
      bulkFavorite.addEventListener("click", favoriteSelected);
    }
    var bulkExport = doc("v2InvBulkExport");
    if (bulkExport) {
      bulkExport.addEventListener("click", function () {
        exportInventory(true);
      });
    }
    var bulkClear = doc("v2InvBulkClear");
    if (bulkClear) {
      bulkClear.addEventListener("click", function () {
        state.inventory.selected = {};
        renderDeviceTable(doc("v2InvTableBody"), state.inventory.list || [], { selectable: true });
        updateBulkBar();
      });
    }
    var refresh = doc("v2InvRefresh");
    if (refresh) {
      refresh.addEventListener("click", loadInventory);
    }
    var exportAll = doc("v2InvExport");
    if (exportAll) {
      exportAll.addEventListener("click", function () {
        exportInventory(false);
      });
    }
    var scan = doc("v2InvScan");
    if (scan) {
      scan.addEventListener("click", function () {
        runInventoryScan(scan);
      });
    }
    var prev = doc("v2InvPrev");
    if (prev) {
      prev.addEventListener("click", function () {
        state.inventory.offset = Math.max(0, state.inventory.offset - state.inventory.limit);
        loadInventory();
      });
    }
    var next = doc("v2InvNext");
    if (next) {
      next.addEventListener("click", function () {
        state.inventory.offset += state.inventory.limit;
        loadInventory();
      });
    }
  }
  /* --------------------------------------------------------------- MAC lookup */

  var MAC_KIND_LABELS = {
    full: "完整 MAC",
    prefix: "6 位前缀",
    suffix: "后缀",
    any: "包含片段",
    empty: "等待输入"
  };

  function macKindLabel(kind) {
    return D.tr(MAC_KIND_LABELS[kind] || "等待输入");
  }

  function updateMacHint() {
    var input = doc("v2MacInput");
    var hint = doc("v2MacHint");
    if (!input || !hint) {
      return;
    }
    var parsed = D.macKind(input.value);
    if (parsed.kind === "empty") {
      hint.textContent = D.tr("等待输入");
      return;
    }
    if (parsed.compact.length < 4) {
      hint.textContent = D.tr("至少输入 4 位十六进制字符。");
      return;
    }
    hint.textContent = macKindLabel(parsed.kind) + " · " + D.tr("有效十六进制 ") + parsed.compact.length + D.tr(" 位");
  }

  function vendorText(value) {
    return value ? D.tr(value) : D.tr("未知厂商");
  }

  function renderVendorNote(prefixes) {
    var note = doc("v2MacVendor");
    if (!note) {
      return;
    }
    var list = prefixes || [];
    if (!list.length) {
      note.hidden = true;
      note.textContent = "";
      return;
    }
    note.hidden = false;
    D.clear(note);
    note.appendChild(D.el("strong", "", D.tr("厂商前缀匹配")));
    var shown = list.slice(0, 8).map(function (item) {
      return item.prefix + " " + vendorText(item.vendor);
    });
    note.appendChild(D.el("span", "", shown.join(" · ") + (list.length > 8 ? " …" : "")));
  }

  function macResultCard(match) {
    var card = D.el("article", "v2-result-card");
    var head = D.el("div", "v2-result-head");
    var title = D.el("div", "v2-name-line");
    title.appendChild(D.el("strong", "", D.deviceName(match)));
    title.appendChild(D.statusBadge(match.status, D.statusReason(match)));
    if (match.live) {
      title.appendChild(D.el("span", "v2-mini-badge", D.tr("扫描结果")));
    }
    if (match.random_mac) {
      title.appendChild(D.el("span", "v2-mini-badge", D.tr("随机 MAC")));
    }
    head.appendChild(title);
    card.appendChild(head);
    var grid = D.el("div", "v2-result-grid");
    var rows = [
      [D.tr("IP 地址"), match.ip || "--"],
      [D.tr("MAC 地址"), match.mac || "--"],
      [D.tr("厂商"), vendorText(match.vendor)],
      [
        D.tr("网段"),
        match.network_id ? String(match.network_id).split("|").pop() : (match.interface || "--")
      ]
    ];
    rows.forEach(function (pair) {
      var cell = D.el("div", "v2-result-cell");
      cell.appendChild(D.el("span", "v2-muted", pair[0]));
      cell.appendChild(D.el("code", "", pair[1]));
      grid.appendChild(cell);
    });
    card.appendChild(grid);
    if (Array.isArray(match.matched_macs) && match.matched_macs.length > 1) {
      card.appendChild(
        D.el("p", "v2-hint", D.tr("匹配到 ") + match.matched_macs.length + D.tr(" 个历史 MAC：") + match.matched_macs.join(D.tr("、")))
      );
    }
    var actions = D.el("div", "v2-inline-actions");
    if (match.device_id) {
      var detail = D.el("button", "v2-button", D.tr("打开设备详情"));
      detail.type = "button";
      detail.addEventListener("click", function () {
        openDevice(match.device_id);
      });
      actions.appendChild(detail);
    } else if (match.live) {
      actions.appendChild(D.el("span", "v2-muted", D.tr("来自当前扫描结果，尚未写入设备档案。")));
    }
    if (match.ip) {
      actions.appendChild(makeCopyButton(match.ip, "IP"));
    }
    if (match.mac) {
      actions.appendChild(makeCopyButton(match.mac, "MAC"));
    }
    card.appendChild(actions);
    return card;
  }

  function renderMacGroup(result) {
    var wrapper = D.el("section", "v2-result-group");
    var header = D.el("header", "v2-result-group-head");
    header.appendChild(D.el("strong", "", result.query || ""));
    header.appendChild(D.el("span", "v2-count", result.count || 0));
    wrapper.appendChild(header);
    if (result.error) {
      wrapper.appendChild(D.el("p", "v2-warning", result.error));
      return wrapper;
    }
    if (result.mode) {
      wrapper.appendChild(D.el("p", "v2-hint", macKindLabel(result.mode)));
    }
    (result.matches || []).forEach(function (match) {
      wrapper.appendChild(macResultCard(match));
    });
    if (!(result.matches || []).length) {
      wrapper.appendChild(D.el("div", "v2-empty-state", D.tr("没有找到匹配设备。")));
    }
    return wrapper;
  }

  function renderMacResults(payload, batch) {
    var container = doc("v2MacResults");
    var empty = doc("v2MacEmpty");
    if (!container) {
      return;
    }
    D.clear(container);
    var groups = batch ? (payload.results || []) : [payload];
    var total = 0;
    groups.forEach(function (group) {
      total += group.count || (group.matches || []).length;
    });
    D.setText("v2MacCount", total);
    if (empty) {
      empty.hidden = total > 0;
      if (!total) {
        empty.textContent = D.tr("没有找到匹配设备。可先运行网络扫描，或改用更短的后缀。");
      }
    }
    groups.forEach(function (group) {
      container.appendChild(renderMacGroup(group));
    });
    var first = groups[0] || {};
    renderVendorNote(first.vendor_prefixes || []);
  }

  function resetMacResults(message) {
    var container = doc("v2MacResults");
    if (container) {
      D.clear(container);
    }
    D.setText("v2MacCount", 0);
    var empty = doc("v2MacEmpty");
    if (empty) {
      empty.hidden = false;
      empty.textContent = message || D.tr("输入 MAC 后开始查询。");
    }
    renderVendorNote([]);
  }

  async function runMacSearch() {
    var input = doc("v2MacInput");
    var batch = doc("v2MacBatch");
    var batchToggle = doc("v2MacBatchToggle");
    var mode = doc("v2MacMode");
    var isBatch = !!(batchToggle && batchToggle.checked);
    var button = doc("v2MacSearch");
    var query = input ? input.value.trim() : "";
    var lines = isBatch && batch
      ? batch.value.split(/\r?\n/).map(function (line) { return line.trim(); }).filter(Boolean)
      : [];
    if (isBatch && !lines.length) {
      D.toast(D.tr("请每行输入一个 MAC、前缀或后缀。"), true);
      return;
    }
    if (!isBatch && !query) {
      D.toast(D.tr("请输入 MAC、前缀或后缀。"), true);
      return;
    }
    setBusy(button, true, D.tr("查询中…"));
    renderVendorNote([]);
    try {
      var payload;
      if (isBatch) {
        payload = await D.API.macBatch(lines);
        renderMacResults(payload, true);
        var total = (payload.results || []).reduce(function (sum, item) {
          return sum + (item.count || 0);
        }, 0);
        D.toast(D.tr("批量查询完成，共匹配 ") + D.countDevices(total), false);
      } else {
        payload = await D.API.macLookup(query, mode ? mode.value : "auto");
        renderMacResults(payload, false);
        D.toast(
          payload.count
            ? D.tr("找到 ") + D.countDevices(payload.count)
            : D.tr("没有找到匹配设备"),
          !payload.count
        );
      }
    } catch (error) {
      resetMacResults(error.message || D.tr("查询失败"));
      D.toast(error.message || D.tr("查询失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  function clearMacLookup() {
    var input = doc("v2MacInput");
    var batch = doc("v2MacBatch");
    var hint = doc("v2MacHint");
    if (input) {
      input.value = "";
    }
    if (batch) {
      batch.value = "";
    }
    if (hint) {
      hint.textContent = D.tr("等待输入");
    }
    resetMacResults(D.tr("输入 MAC 后开始查询。"));
  }

  function bindMac() {
    var input = doc("v2MacInput");
    if (input) {
      input.addEventListener("input", debounce(updateMacHint, 120));
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          runMacSearch();
        }
      });
    }
    var toggle = doc("v2MacBatchToggle");
    var batch = doc("v2MacBatch");
    if (toggle) {
      toggle.addEventListener("change", function () {
        if (batch) {
          batch.hidden = !toggle.checked;
          if (toggle.checked) {
            batch.focus();
          }
        }
      });
    }
    var search = doc("v2MacSearch");
    if (search) {
      search.addEventListener("click", runMacSearch);
    }
    var clear = doc("v2MacClear");
    if (clear) {
      clear.addEventListener("click", clearMacLookup);
    }
  }
  /* ----------------------------------------------------------------- analysis */

  function pingSummary(payload) {
    if (!payload) {
      return D.tr("尚未测试");
    }
    if (!payload.reachable) {
      return D.tr("不可达") + " · " + D.tr("丢包 ") + (payload.loss_percent || 100) + "%";
    }
    var avg = payload.avg_ms === null || payload.avg_ms === undefined ? "--" : payload.avg_ms + " ms";
    var min = payload.min_ms === null || payload.min_ms === undefined ? "--" : payload.min_ms;
    var max = payload.max_ms === null || payload.max_ms === undefined ? "--" : payload.max_ms;
    return D.tr("可达") + " · " + D.tr("平均 ") + avg +
      " · " + D.tr("范围 ") + min + "–" + max + " ms" +
      " · " + D.tr("丢包 ") + (payload.loss_percent || 0) + "%" +
      " · " + (payload.received || 0) + "/" + (payload.transmitted || 0);
  }

  function renderPing(payload) {
    var target = doc("v2PingResult");
    if (!target) {
      return;
    }
    target.className = "v2-ping-result " + (payload && payload.reachable ? "is-reachable" : "is-unreachable");
    D.clear(target);
    var head = D.el("div", "v2-name-line");
    head.appendChild(D.el("strong", "", payload && payload.host ? payload.host : D.tr("目标")));
    head.appendChild(D.el("span", "v2-muted", pingSummary(payload)));
    target.appendChild(head);
    if (payload) {
      var meta = D.el("p", "v2-hint", D.tr("测试时间 ") + D.formatTime(payload.measured_at, false));
      target.appendChild(meta);
    }
  }

  async function runPing() {
    var hostInput = doc("v2PingHost");
    var countSelect = doc("v2PingCount");
    var button = doc("v2PingRun");
    var host = hostInput ? hostInput.value.trim() : "";
    if (!host) {
      D.toast(D.tr("请输入要测试的 IP 或主机名。"), true);
      return;
    }
    setBusy(button, true, D.tr("测试中…"));
    try {
      var payload = await D.API.ping({
        host: host,
        count: countSelect ? Number(countSelect.value) || 4 : 4
      });
      renderPing(payload);
      D.toast(pingSummary(payload), !payload.reachable);
    } catch (error) {
      renderPing({ host: host, reachable: false, loss_percent: 100, transmitted: 0, received: 0 });
      D.toast(error.message || D.tr("Ping 失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  async function testGateway() {
    var button = doc("v2GatewayTest");
    setBusy(button, true, D.tr("检测中…"));
    try {
      var payload = await D.API.ping({ gateway: true, count: 4 });
      renderPing(payload);
      D.toast(pingSummary(payload), !payload.reachable);
    } catch (error) {
      var target = doc("v2PingResult");
      if (target) {
        target.className = "v2-ping-result is-unreachable";
        target.textContent = error.message || D.tr("网关检测失败");
      }
      D.toast(error.message || D.tr("网关检测失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  function renderAnalysis(payload) {
    state.analysis = payload;
    var interfaces = payload.interfaces || [];
    var dns = payload.dns_servers || [];
    var networks = payload.networks || [];
    var warnings = payload.warnings || [];
    D.setText(
      "v2AnalysisSummary",
      D.countUnit(interfaces.length, " 个接口", "interface", "interfaces") +
        " · " + D.countNetworks(networks.length) +
        " · " + D.countUnit(dns.length, " 个 DNS", "DNS server", "DNS servers")
    );
    var warningBox = doc("v2AnalysisWarnings");
    if (warningBox) {
      warningBox.hidden = warnings.length === 0;
      warningBox.textContent = warnings.map(function (item) { return D.tr(item); }).join(D.tr("；"));
    }

    var interfaceList = doc("v2AnalysisInterfaces");
    var interfaceEmpty = doc("v2AnalysisInterfacesEmpty");
    if (interfaceList) {
      D.clear(interfaceList);
      interfaces.forEach(function (item) {
        var row = D.el("div", "v2-list-row v2-list-stack");
        var main = D.el("div", "v2-list-main");
        main.appendChild(D.el("strong", "", item.interface + " · " + item.local_ip + "/" + item.prefix_length));
        main.appendChild(
          D.el(
            "span",
            "v2-subtle",
            D.tr("范围 ") + item.scan_range +
              " · " + D.tr("网关 ") + (item.gateway || D.tr("无")) +
              " · " + D.tr("设备 ") + (item.device_count || 0) + D.tr("（") + D.tr("在线 ") + (item.online_count || 0) + D.tr("）")
          )
        );
        main.appendChild(D.el("span", "v2-subtle", D.tr("本机 MAC ") + (item.local_mac || "--")));
        row.appendChild(main);
        interfaceList.appendChild(row);
      });
      if (interfaceEmpty) {
        interfaceEmpty.hidden = interfaces.length > 0;
      }
    }

    var gatewayList = doc("v2AnalysisGateway");
    if (gatewayList) {
      D.clear(gatewayList);
      interfaces.forEach(function (item) {
        var row = D.el("div", "v2-list-row");
        row.appendChild(D.el("strong", "", item.interface));
        row.appendChild(D.el("code", "", item.gateway || D.tr("无默认网关")));
        gatewayList.appendChild(row);
      });
      if (!interfaces.length) {
        gatewayList.appendChild(D.el("div", "v2-empty", D.tr("没有可用的默认网关。")));
      }
    }

    var dnsList = doc("v2AnalysisDns");
    var dnsEmpty = doc("v2AnalysisDnsEmpty");
    if (dnsList) {
      D.clear(dnsList);
      dns.forEach(function (server) {
        var row = D.el("div", "v2-list-row");
        row.appendChild(D.el("strong", "", server));
        dnsList.appendChild(row);
      });
      if (dnsEmpty) {
        dnsEmpty.hidden = dns.length > 0;
      }
    }

    var networkBox = doc("v2AnalysisNetworks");
    var networkEmpty = doc("v2AnalysisNetworksEmpty");
    if (networkBox) {
      D.clear(networkBox);
      if (networks.length) {
        var table = D.el("table", "v2-table");
        var thead = D.el("thead");
        var headRow = D.el("tr");
        ["接口", "网段", "总数", "在线", "离线", "未知"].forEach(function (label) {
          headRow.appendChild(D.el("th", "", D.tr(label)));
        });
        thead.appendChild(headRow);
        table.appendChild(thead);
        var tbody = D.el("tbody");
        networks.forEach(function (item) {
          var tr = D.el("tr");
          var parts = String(item.network_id || "").split("|");
          tr.appendChild(D.el("td", "", parts.length > 1 ? parts[0] : "--"));
          tr.appendChild(D.el("td", "", parts.length > 1 ? parts.slice(1).join("|") : (item.network_id || "--")));
          tr.appendChild(D.el("td", "", item.total || 0));
          tr.appendChild(D.el("td", "", item.online || 0));
          tr.appendChild(D.el("td", "", item.offline || 0));
          tr.appendChild(D.el("td", "", item.unknown || 0));
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        networkBox.appendChild(table);
      }
      if (networkEmpty) {
        networkEmpty.hidden = networks.length > 0;
      }
    }

    var vendorList = doc("v2AnalysisVendors");
    var vendorEmpty = doc("v2AnalysisVendorsEmpty");
    if (vendorList) {
      D.clear(vendorList);
      (payload.vendors || []).forEach(function (item) {
        var row = D.el("div", "v2-list-row");
        row.appendChild(D.el("strong", "", vendorText(item.vendor)));
        row.appendChild(D.el("span", "v2-count", item.count || 0));
        vendorList.appendChild(row);
      });
      if (vendorEmpty) {
        vendorEmpty.hidden = (payload.vendors || []).length > 0;
      }
    }
  }

  async function loadAnalysis() {
    try {
      var payload = await D.API.analysis();
      renderAnalysis(payload);
    } catch (error) {
      D.setText("v2AnalysisSummary", D.tr("加载失败"));
      D.toast(error.message || D.tr("网络分析加载失败"), true);
    }
  }

  function bindAnalysis() {
    var refresh = doc("v2AnalysisRefresh");
    if (refresh) {
      refresh.addEventListener("click", loadAnalysis);
    }
    var gateway = doc("v2GatewayTest");
    if (gateway) {
      gateway.addEventListener("click", testGateway);
    }
    var run = doc("v2PingRun");
    if (run) {
      run.addEventListener("click", runPing);
    }
    var host = doc("v2PingHost");
    if (host) {
      host.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          runPing();
        }
      });
    }
  }
  /* ------------------------------------------------------------------ history */

  var TASK_STATUS_LABELS = {
    completed: "已完成",
    stopped: "已中断",
    error: "失败",
    running: "进行中"
  };

  function taskStatusLabel(status) {
    return D.tr(TASK_STATUS_LABELS[status] || status || "未知");
  }

  function taskScope(task, compact) {
    var parts = [];
    (task.networks || []).forEach(function (network) {
      if (network && network.scan_range) {
        parts.push(compact || !network.interface ? network.scan_range : network.interface + " " + network.scan_range);
      }
    });
    (task.custom_ranges || []).forEach(function (value) {
      parts.push(value);
    });
    if (!parts.length && (task.network_ids || []).length) {
      parts = task.network_ids.slice();
    }
    if ((task.suffixes || []).length) {
      parts.push(D.tr("后缀 ") + task.suffixes.join(D.tr("、")));
    }
    return parts.length ? parts.join(D.tr("；")) : "--";
  }

  function renderHistory(payload) {
    var tasks = payload.tasks || [];
    state.history.tasks = tasks;
    D.setText(
      "v2HistorySummary",
      D.tr("共 ") + D.countTasks(payload.total || tasks.length) +
        (tasks.length ? " · " + D.tr("最近 ") + D.formatTime(tasks[0].finished_at, true) : "")
    );
    var tbody = doc("v2HistoryTableBody");
    var empty = doc("v2HistoryEmpty");
    if (tbody) {
      D.clear(tbody);
      tasks.forEach(function (task) {
        var row = D.el("tr");
        row.appendChild(D.el("td", "", D.formatTime(task.finished_at, false)));
        row.appendChild(D.el("td", "", D.kindLabel(task.kind) || task.kind || "--"));
        var scopeCell = D.el("td", "v2-scope-cell");
        scopeCell.appendChild(D.el("span", "", taskScope(task, true)));
        row.appendChild(scopeCell);
        var statusCell = D.el("td");
        statusCell.appendChild(
          D.el("span", "v2-task-status v2-task-status--" + (task.status || "unknown"), taskStatusLabel(task.status))
        );
        row.appendChild(statusCell);
        row.appendChild(D.el("td", "", task.discovered || 0));
        row.appendChild(D.el("td", "", task.new_devices || 0));
        row.appendChild(D.el("td", "", task.offline_devices || 0));
        row.appendChild(D.el("td", "", task.ip_changes || 0));
        row.appendChild(D.el("td", "", D.formatDuration(task.started_at, task.finished_at)));
        var actionCell = D.el("td", "v2-actions-cell");
        var detail = D.el("button", "v2-text-button", D.tr("详情"));
        detail.type = "button";
        detail.setAttribute("data-task-id", task.task_id || "");
        actionCell.appendChild(detail);
        row.appendChild(actionCell);
        tbody.appendChild(row);
      });
    }
    if (empty) {
      empty.hidden = tasks.length > 0;
    }
  }

  async function loadHistory() {
    try {
      var payload = await D.API.scans(100);
      renderHistory(payload);
    } catch (error) {
      D.setText("v2HistorySummary", D.tr("加载失败"));
      D.toast(error.message || D.tr("扫描历史加载失败"), true);
    }
  }

  function historyField(label, value) {
    var item = D.el("div");
    item.appendChild(D.el("dt", "", D.tr(label)));
    item.appendChild(D.el("dd", "", value === undefined || value === null || value === "" ? "--" : value));
    return item;
  }

  function renderHistoryDetail(task) {
    state.history.detail = task;
    var section = doc("v2HistoryDetail");
    var body = doc("v2HistoryDetailBody");
    if (!section || !body) {
      return;
    }
    D.setText(
      "v2HistoryDetailTitle",
      (D.kindLabel(task.kind) || task.kind || D.tr("任务详情")) + " · " + D.formatTime(task.finished_at, false)
    );
    D.clear(body);
    var summary = D.el("dl", "v2-about v2-detail-grid");
    summary.appendChild(historyField("任务 ID", task.task_id));
    summary.appendChild(historyField("状态", taskStatusLabel(task.status)));
    summary.appendChild(historyField("开始时间", D.formatTime(task.started_at, false)));
    summary.appendChild(historyField("完成时间", D.formatTime(task.finished_at, false)));
    summary.appendChild(historyField("扫描范围", taskScope(task)));
    summary.appendChild(historyField("探测主机", (task.probed_hosts || 0) + " / " + (task.total_hosts || 0)));
    summary.appendChild(historyField("发现设备", task.discovered || 0));
    summary.appendChild(historyField("新增设备", task.new_devices || 0));
    summary.appendChild(historyField("离线设备", task.offline_devices || 0));
    summary.appendChild(historyField("IP 变化", task.ip_changes || 0));
    if (task.error) {
      summary.appendChild(historyField("错误", task.error));
    }
    body.appendChild(summary);
    if ((task.warnings || []).length) {
      var warning = D.el("div", "v2-warning", task.warnings.map(function (item) { return D.tr(item); }).join(D.tr("；")));
      body.appendChild(warning);
    }
    var results = task.results || [];
    if (results.length) {
      var wrap = D.el("div", "v2-table-wrap");
      var table = D.el("table", "v2-table");
      var thead = D.el("thead");
      var headRow = D.el("tr");
      ["网卡", "扫描范围", "IP 地址", "MAC 地址", "状态"].forEach(function (label) {
        headRow.appendChild(D.el("th", "", D.tr(label)));
      });
      thead.appendChild(headRow);
      table.appendChild(thead);
      var tbody = D.el("tbody");
      results.forEach(function (item) {
        var tr = D.el("tr");
        tr.appendChild(D.el("td", "", item.interface || "--"));
        tr.appendChild(D.el("td", "", item.scan_range || "--"));
        tr.appendChild(D.el("td", "", item.ip || "--"));
        tr.appendChild(D.el("td", "", item.mac || "--"));
        tr.appendChild(D.el("td", "", D.stateLabel(item.state) || item.state || "--"));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      body.appendChild(wrap);
    } else {
      body.appendChild(D.el("div", "v2-empty-state", D.tr("该任务没有保存扫描结果。")));
    }
    section.hidden = false;
    if (section.scrollIntoView) {
      section.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  async function showHistoryDetail(taskId) {
    if (!taskId) {
      return;
    }
    try {
      var payload = await D.API.scan(taskId);
      if (!payload.task) {
        throw new Error(D.tr("扫描任务不存在"));
      }
      renderHistoryDetail(payload.task);
    } catch (error) {
      D.toast(error.message || D.tr("任务详情加载失败"), true);
    }
  }

  function exportHistoryDetail() {
    var task = state.history.detail;
    if (!task) {
      return;
    }
    if (!(task.results || []).length) {
      D.toast(D.tr("该任务没有可导出的扫描结果。"), true);
      return;
    }
    D.exportResults(task.results, appSettings(), "network-locator-scan-" + task.task_id);
  }

  async function purgeHistory() {
    if (!window.confirm(D.tr("将清理超过历史保留天数的扫描记录，设备档案不会被删除。继续？"))) {
      return;
    }
    try {
      var payload = await D.API.purgeScans();
      D.toast(D.tr("已清理 ") + (payload.removed || 0) + D.tr(" 条扫描记录"), false);
      await loadHistory();
    } catch (error) {
      D.toast(error.message || D.tr("清理历史失败"), true);
    }
  }

  function bindHistory() {
    var refresh = doc("v2HistoryRefresh");
    if (refresh) {
      refresh.addEventListener("click", loadHistory);
    }
    var purge = doc("v2HistoryPurge");
    if (purge) {
      purge.addEventListener("click", purgeHistory);
    }
    var tbody = doc("v2HistoryTableBody");
    if (tbody) {
      tbody.addEventListener("click", function (event) {
        var button = event.target.closest("[data-task-id]");
        if (button) {
          showHistoryDetail(button.getAttribute("data-task-id"));
        }
      });
    }
    var close = doc("v2HistoryDetailClose");
    if (close) {
      close.addEventListener("click", function () {
        var section = doc("v2HistoryDetail");
        if (section) {
          section.hidden = true;
        }
        state.history.detail = null;
      });
    }
    var exportButton = doc("v2HistoryDetailExport");
    if (exportButton) {
      exportButton.addEventListener("click", exportHistoryDetail);
    }
  }
  /* ----------------------------------------------------------------- settings */

  function settingValue(id) {
    var node = doc(id);
    return node ? node.value : "";
  }

  function settingChecked(id) {
    var node = doc(id);
    return !!(node && node.checked);
  }

  function populateSettingsInterfaces(interfaces, selected) {
    var select = doc("v2SetInterface");
    if (!select) {
      return;
    }
    D.clear(select);
    var auto = D.el("option", "", D.tr("自动选择"));
    auto.value = "";
    select.appendChild(auto);
    (interfaces || []).forEach(function (item) {
      var option = D.el("option", "", item.interface + " · " + item.scan_range);
      option.value = item.interface;
      select.appendChild(option);
    });
    var wanted = String(selected || "");
    var found = false;
    for (var index = 0; index < select.options.length; index += 1) {
      if (select.options[index].value === wanted) {
        select.selectedIndex = index;
        found = true;
        break;
      }
    }
    if (!found && wanted) {
      var extra = D.el("option", "", wanted + D.tr("（当前配置）"));
      extra.value = wanted;
      select.appendChild(extra);
      select.value = wanted;
    } else if (!found) {
      select.value = "";
    }
  }

  function renderSettings(payload) {
    var settings = payload.settings || {};
    var storage = payload.storage || {};
    if (doc("v2SetTimeout")) {
      doc("v2SetTimeout").value = settings.scan_timeout_ms || "";
    }
    if (doc("v2SetConcurrency")) {
      doc("v2SetConcurrency").value = settings.scan_concurrency || "";
    }
    if (doc("v2SetStale")) {
      doc("v2SetStale").value = settings.stale_after_minutes || "";
    }
    if (doc("v2SetAutoScan")) {
      doc("v2SetAutoScan").checked = !!settings.auto_scan_enabled;
    }
    if (doc("v2SetAutoInterval")) {
      doc("v2SetAutoInterval").value = settings.auto_scan_interval_minutes || "";
    }
    if (doc("v2SetDelimiter")) {
      doc("v2SetDelimiter").value = settings.csv_delimiter || ",";
    }
    if (doc("v2SetCsvHeader")) {
      doc("v2SetCsvHeader").checked = settings.csv_include_header !== false;
    }
    if (doc("v2SetCsvBom")) {
      doc("v2SetCsvBom").checked = settings.csv_bom !== false;
    }
    D.setText("v2SetStoragePath", storage.path || "--");
    D.setText("v2SetStorageSize", D.formatBytes(storage.size_bytes || 0));
    D.setText("v2SetSchema", "v" + (payload.schema_version || "--"));
    D.setText("v2SetRetention", (settings.history_retention_days || 0) + D.tr(" 天"));
    D.setText("v2AboutVendors", payload.vendor_count || 0);
    D.setText(
      "v2SettingsSummary",
      D.tr("设置已保存 · 超时 ") + (settings.scan_timeout_ms || 0) + " ms" +
        " · " + D.tr("并发 ") + (settings.scan_concurrency || 0)
    );
  }

  async function loadSettings() {
    try {
      var payload = await D.API.settings();
      state.settings = payload;
      renderSettings(payload);
      applyAutoScan(payload.settings || {});
      try {
        var analysis = await D.API.analysis();
        populateSettingsInterfaces(analysis.interfaces || [], (payload.settings || {}).default_interface);
      } catch (error) {
        populateSettingsInterfaces([], (payload.settings || {}).default_interface);
      }
    } catch (error) {
      D.setText("v2SettingsSummary", D.tr("设置加载失败"));
      D.toast(error.message || D.tr("设置加载失败"), true);
    }
  }

  function currentThemeChoice() {
    try {
      var value = window.localStorage.getItem("networkLocator.theme.v1") || "";
      return value === "light" || value === "dark" || value === "system" ? value : "system";
    } catch (error) {
      return "system";
    }
  }

  function settingsPatch() {
    return {
      scan_timeout_ms: Number(settingValue("v2SetTimeout")),
      scan_concurrency: Number(settingValue("v2SetConcurrency")),
      default_interface: settingValue("v2SetInterface"),
      stale_after_minutes: Number(settingValue("v2SetStale")),
      auto_scan_enabled: settingChecked("v2SetAutoScan"),
      auto_scan_interval_minutes: Number(settingValue("v2SetAutoInterval")),
      csv_delimiter: settingValue("v2SetDelimiter") || ",",
      csv_include_header: settingChecked("v2SetCsvHeader"),
      csv_bom: settingChecked("v2SetCsvBom"),
      theme: currentThemeChoice()
    };
  }

  function validateSettings(patch) {
    var numeric = [
      ["scan_timeout_ms", 100, 30000],
      ["scan_concurrency", 1, 128],
      ["stale_after_minutes", 1, 10080],
      ["auto_scan_interval_minutes", 1, 1440]
    ];
    for (var index = 0; index < numeric.length; index += 1) {
      var item = numeric[index];
      if (!isFinite(patch[item[0]]) || patch[item[0]] < item[1] || patch[item[0]] > item[2]) {
        return D.tr(item[0]) + D.tr(" 必须在 ") + item[1] + "–" + item[2] + D.tr(" 之间");
      }
    }
    return "";
  }

  async function saveSettings() {
    var button = doc("v2SettingsSave");
    var patch = settingsPatch();
    var problem = validateSettings(patch);
    if (problem) {
      D.toast(problem, true);
      return;
    }
    setBusy(button, true, D.tr("保存中…"));
    try {
      var payload = await D.API.updateSettings(patch);
      state.settings = state.settings || {};
      state.settings.settings = payload.settings || payload;
      renderSettings({
        settings: payload.settings || payload,
        storage: (state.settings && state.settings.storage) || {},
        schema_version: (state.settings && state.settings.schema_version) || "",
        vendor_count: (state.settings && state.settings.vendor_count) || 0
      });
      applyAutoScan(payload.settings || payload);
      D.toast(D.tr("设置已保存"), false);
    } catch (error) {
      D.toast(error.message || D.tr("设置保存失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  function applyAutoScan(settings) {
    if (state.autoScanTimer) {
      window.clearInterval(state.autoScanTimer);
      state.autoScanTimer = null;
    }
    if (!settings || !settings.auto_scan_enabled) {
      return;
    }
    var minutes = Math.max(1, Number(settings.auto_scan_interval_minutes) || 30);
    state.autoScanTimer = window.setInterval(runAutoScan, minutes * 60 * 1000);
  }

  async function runAutoScan() {
    if (state.autoScanRunning) {
      return;
    }
    state.autoScanRunning = true;
    try {
      var payload = await D.API.inventoryScan({});
      var task = payload.task || {};
      D.toast(
        D.tr("自动扫描完成：发现 ") + (task.discovered || 0) +
          D.tr(" 台，新增 ") + (task.new_devices || 0) + D.tr(" 台"),
        false
      );
      if (state.route === "dashboard" || state.route === "inventory") {
        refreshCurrent();
      }
    } catch (error) {
      D.toast(D.tr("自动扫描失败：") + (error.message || D.tr("未知错误")), true);
    } finally {
      state.autoScanRunning = false;
    }
  }

  async function purgeFromSettings() {
    if (!window.confirm(D.tr("将清理超过历史保留天数的扫描记录，设备档案不会被删除。继续？"))) {
      return;
    }
    try {
      var payload = await D.API.purgeScans();
      D.toast(D.tr("已清理 ") + (payload.removed || 0) + D.tr(" 条扫描记录"), false);
      await loadSettings();
    } catch (error) {
      D.toast(error.message || D.tr("清理历史失败"), true);
    }
  }

  function bindSettings() {
    var save = doc("v2SettingsSave");
    if (save) {
      save.addEventListener("click", saveSettings);
    }
    var reload = doc("v2SettingsReload");
    if (reload) {
      reload.addEventListener("click", loadSettings);
    }
    var purge = doc("v2SetPurge");
    if (purge) {
      purge.addEventListener("click", purgeFromSettings);
    }
  }
  /* ------------------------------------------------------------------- drawer */

  function drawerField(label, value) {
    var item = D.el("div");
    item.appendChild(D.el("dt", "", D.tr(label)));
    item.appendChild(D.el("dd", "", value === undefined || value === null || value === "" ? "--" : value));
    return item;
  }

  function drawerTable(headers, rows) {
    var wrap = D.el("div", "v2-table-wrap");
    var table = D.el("table", "v2-table v2-mini-table");
    var thead = D.el("thead");
    var headRow = D.el("tr");
    headers.forEach(function (label) {
      headRow.appendChild(D.el("th", "", D.tr(label)));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = D.el("tbody");
    rows.forEach(function (values) {
      var row = D.el("tr");
      values.forEach(function (value) {
        row.appendChild(D.el("td", "", value === undefined || value === null || value === "" ? "--" : value));
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function setDrawerControlsEnabled(enabled) {
    ["v2DrawerSave", "v2DrawerCopyIp", "v2DrawerCopyMac"].forEach(function (id) {
      var node = doc(id);
      if (node) {
        node.disabled = !enabled;
      }
    });
  }

  function setDrawerContentVisible(visible) {
    var edit = document.querySelector("#v2Drawer .v2-drawer-edit");
    var reason = doc("v2DrawerStatusReason");
    var summary = doc("v2DrawerSummary");
    if (edit) {
      edit.hidden = !visible;
    }
    if (reason) {
      reason.hidden = !visible;
    }
    if (summary) {
      summary.hidden = !visible;
    }
    var sections = document.querySelectorAll("#v2Drawer .v2-drawer-section");
    for (var index = 0; index < sections.length; index += 1) {
      sections[index].hidden = !visible;
    }
  }

  function resetDrawerHeader() {
    D.setText("v2DrawerName", D.tr("设备详情"));
    var status = doc("v2DrawerStatus");
    if (status) {
      D.clear(status);
      status.className = "v2-badge";
    }
    var reason = doc("v2DrawerStatusReason");
    if (reason) {
      reason.textContent = "";
    }
  }

  function clearDrawerFields() {
    var nameInput = doc("v2DrawerNameInput");
    var noteInput = doc("v2DrawerNoteInput");
    var favorite = doc("v2DrawerFavorite");
    if (nameInput) {
      nameInput.value = "";
    }
    if (noteInput) {
      noteInput.value = "";
    }
    if (favorite) {
      favorite.checked = false;
    }
    ["v2DrawerSummary", "v2DrawerAddresses", "v2DrawerIpHistory", "v2DrawerEvents"].forEach(function (id) {
      var node = doc(id);
      if (node) {
        D.clear(node);
      }
    });
  }

  function showDrawerLoading() {
    var loading = doc("v2DrawerLoading");
    var error = doc("v2DrawerError");
    if (loading) {
      loading.hidden = false;
    }
    if (error) {
      error.hidden = true;
    }
    resetDrawerHeader();
    clearDrawerFields();
    setDrawerContentVisible(false);
    var body = document.querySelector("#v2Drawer .v2-drawer-body");
    if (body) {
      body.scrollTop = 0;
    }
    setDrawerControlsEnabled(false);
  }

  function showDrawerError(message) {
    var loading = doc("v2DrawerLoading");
    var error = doc("v2DrawerError");
    var text = doc("v2DrawerErrorText");
    var target = doc("v2DrawerSaveState");
    if (loading) {
      loading.hidden = true;
    }
    if (error) {
      error.hidden = false;
    }
    if (text) {
      text.textContent = message || D.tr("设备详情加载失败");
    }
    if (target) {
      target.textContent = message || D.tr("设备详情加载失败");
    }
    resetDrawerHeader();
    clearDrawerFields();
    setDrawerContentVisible(false);
    setDrawerControlsEnabled(false);
  }

  function renderDrawer(device) {
    if (!device) {
      return;
    }
    var loading = doc("v2DrawerLoading");
    var error = doc("v2DrawerError");
    if (loading) {
      loading.hidden = true;
    }
    if (error) {
      error.hidden = true;
    }
    setDrawerContentVisible(true);
    setDrawerControlsEnabled(true);
    var name = doc("v2DrawerName");
    var status = doc("v2DrawerStatus");
    var reason = doc("v2DrawerStatusReason");
    if (name) {
      name.textContent = D.deviceName(device);
    }
    if (status) {
      D.clear(status);
      status.className = "v2-badge";
      status.appendChild(D.statusBadge(device.status, D.statusReason(device)));
    }
    if (reason) {
      reason.textContent = D.statusReason(device);
    }
    var nameInput = doc("v2DrawerNameInput");
    var noteInput = doc("v2DrawerNoteInput");
    var favorite = doc("v2DrawerFavorite");
    if (nameInput) {
      nameInput.value = device.display_name || "";
    }
    if (noteInput) {
      noteInput.value = device.note || "";
    }
    if (favorite) {
      favorite.checked = !!device.favorite;
    }
    var summary = doc("v2DrawerSummary");
    if (summary) {
      D.clear(summary);
      summary.appendChild(drawerField("IP 地址", device.ip));
      summary.appendChild(drawerField("MAC 地址", device.mac));
      summary.appendChild(drawerField("厂商", vendorText(device.vendor)));
      summary.appendChild(drawerField("网卡", device.interface));
      summary.appendChild(
        drawerField(
          "网段",
          device.network_id ? String(device.network_id).split("|").pop() : (device.interface || "")
        )
      );
      summary.appendChild(drawerField("状态", D.statusLabel(device.status)));
      summary.appendChild(drawerField("首次发现", D.formatTime(device.first_seen, false)));
      summary.appendChild(drawerField("最近发现", D.formatTime(device.last_seen, false)));
      summary.appendChild(drawerField("最近检测", D.formatTime(device.last_checked, false)));
      summary.appendChild(drawerField("发现次数", device.seen_count || 0));
      summary.appendChild(drawerField("随机 MAC", device.random_mac ? D.tr("是") : D.tr("否")));
      summary.appendChild(drawerField("设备 ID", device.device_id));
    }
    var addresses = doc("v2DrawerAddresses");
    if (addresses) {
      D.clear(addresses);
      var addressItems = device.addresses || [];
      if (!addressItems.length) {
        addresses.appendChild(D.el("div", "v2-empty", D.tr("暂无地址记录。")));
      } else {
        addresses.appendChild(
          drawerTable(
            ["IP 地址", "MAC 地址", "网卡", "最近发现", "状态"],
            addressItems.map(function (item) {
              return [
                item.ip,
                item.mac,
                item.interface,
                D.formatTime(item.last_seen, false),
                item.is_current ? D.tr("当前") : D.tr("历史")
              ];
            })
          )
        );
      }
    }
    var history = doc("v2DrawerIpHistory");
    if (history) {
      D.clear(history);
      var items = device.ip_history || [];
      if (!items.length) {
        history.appendChild(D.el("div", "v2-empty", D.tr("暂无 IP 历史。")));
      } else {
        history.appendChild(
          drawerTable(
            ["IP 地址", "首次发现", "最近发现", "状态"],
            items.map(function (item) {
              return [
                item.ip,
                D.formatTime(item.first_seen, false),
                D.formatTime(item.last_seen, false),
                item.is_current ? D.tr("当前") : D.tr("历史")
              ];
            })
          )
        );
      }
    }
    var events = doc("v2DrawerEvents");
    if (events) {
      D.clear(events);
      var list = device.events || [];
      if (!list.length) {
        events.appendChild(D.el("div", "v2-empty", D.tr("暂无设备事件。")));
      } else {
        list.slice(0, 50).forEach(function (event) {
          var row = D.el("div", "v2-timeline-item");
          row.appendChild(D.el("span", "v2-timeline-dot"));
          var body = D.el("div", "v2-timeline-body");
          var line = D.el("div", "v2-timeline-head");
          line.appendChild(D.el("strong", "", D.eventLabel(event.kind) || event.kind || "--"));
          line.appendChild(D.el("span", "v2-muted", D.formatTime(event.created_at, true)));
          body.appendChild(line);
          var detail = D.eventDetail(event);
          if (detail) {
            body.appendChild(D.el("span", "v2-subtle", detail));
          }
          row.appendChild(body);
          events.appendChild(row);
        });
      }
    }
  }

  async function loadDrawer(deviceId) {
    var token = ++state.drawer.token;
    state.drawer.currentId = deviceId || "";
    var target = doc("v2DrawerSaveState");
    if (target) {
      target.textContent = D.tr("正在读取设备…");
    }
    showDrawerLoading();
    try {
      var payload = await D.API.device(deviceId);
      if (token !== state.drawer.token) {
        return;
      }
      if (!payload.device) {
        throw new Error(D.tr("设备不存在"));
      }
      state.drawer.device = payload.device;
      renderDrawer(payload.device);
      if (target) {
        target.textContent = D.tr("设备档案读取于 ") + D.formatTime(new Date(), false);
      }
    } catch (error) {
      if (token !== state.drawer.token) {
        return;
      }
      state.drawer.device = null;
      showDrawerError(error.message || D.tr("设备详情加载失败"));
      D.toast(error.message || D.tr("设备详情加载失败"), true);
    }
  }

  async function saveDrawer() {
    var device = state.drawer.device;
    if (!device) {
      return;
    }
    var button = doc("v2DrawerSave");
    var stateText = doc("v2DrawerSaveState");
    var nameInput = doc("v2DrawerNameInput");
    var noteInput = doc("v2DrawerNoteInput");
    var favorite = doc("v2DrawerFavorite");
    setBusy(button, true, D.tr("保存中…"));
    if (stateText) {
      stateText.textContent = D.tr("正在保存…");
    }
    try {
      var payload = await D.API.updateDevice(device.device_id, {
        display_name: nameInput ? nameInput.value.trim() : "",
        note: noteInput ? noteInput.value.trim() : "",
        favorite: !!(favorite && favorite.checked)
      });
      state.drawer.device = payload.device;
      renderDrawer(payload.device);
      if (stateText) {
        stateText.textContent = D.tr("已保存 ") + D.formatTime(new Date(), false);
      }
      D.toast(D.tr("设备信息已保存"), false);
      refreshCurrent();
    } catch (error) {
      if (stateText) {
        stateText.textContent = error.message || D.tr("保存失败");
      }
      D.toast(error.message || D.tr("保存失败"), true);
    } finally {
      setBusy(button, false);
    }
  }

  function bindDrawer() {
    var save = doc("v2DrawerSave");
    if (save) {
      save.addEventListener("click", saveDrawer);
    }
    var copyIp = doc("v2DrawerCopyIp");
    if (copyIp) {
      copyIp.addEventListener("click", function () {
        if (state.drawer.device) {
          D.copy(state.drawer.device.ip, "IP");
        }
      });
    }
    var copyMac = doc("v2DrawerCopyMac");
    if (copyMac) {
      copyMac.addEventListener("click", function () {
        if (state.drawer.device) {
          D.copy(state.drawer.device.mac, "MAC");
        }
      });
    }
    var retry = doc("v2DrawerRetry");
    if (retry) {
      retry.addEventListener("click", function () {
        if (state.drawer.currentId) {
          loadDrawer(state.drawer.currentId);
        }
      });
    }
  }
  /* --------------------------------------------------------------- routing/init */

  function onRoute(route) {
    state.route = route || currentRoute();
    if (state.route !== "mac-lookup") {
      closeDevice();
    }
    if (state.route === "dashboard") {
      D.setHidden("v2DashEmpty", true);
      loadDashboard();
    } else if (state.route === "inventory") {
      loadInventory();
    } else if (state.route === "mac-lookup") {
      var input = doc("v2MacInput");
      if (input) {
        window.setTimeout(function () {
          input.focus();
        }, 40);
      }
    } else if (state.route === "analysis") {
      loadAnalysis();
    } else if (state.route === "history") {
      loadHistory();
    } else if (state.route === "settings") {
      loadSettings();
    }
  }

  function bindRoutes() {
    document.addEventListener("networklocator:route", function (event) {
      onRoute(event && event.detail ? event.detail.route : currentRoute());
    });
    document.addEventListener("networklocator:scan-finished", function () {
      if (state.route === "dashboard" || state.route === "inventory" || state.route === "history") {
        refreshCurrent();
      }
    });
  }

  function init() {
    bindDashboard();
    bindInventory();
    bindMac();
    bindAnalysis();
    bindHistory();
    bindSettings();
    bindDrawer();
    bindRoutes();
    onRoute(currentRoute());
  }

  root.NetworkLocatorPages = {
    refresh: onRoute,
    refreshCurrent: refreshCurrent,
    openDevice: openDevice,
    scanInventory: runInventoryScan
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}(typeof window !== "undefined" ? window : globalThis));
