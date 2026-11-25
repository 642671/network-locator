/* Network Locator V2 — shell routing, theme/language settings, dashboard. */
(function () {
  "use strict";

  var APP_ID = "network-locator";
  var THEME_KEY = "networkLocator.theme.v1";
  var ROUTES = {
    dashboard: {
      title: "设备总览",
      subtitle: "查看局域网设备、网段与最近发现情况。"
    },
    discovery: {
      title: "网络扫描",
      subtitle: "识别网段并按 MAC 后缀查找设备。"
    },
    inventory: {
      title: "设备管理",
      subtitle: "维护设备档案、名称、备注与收藏。"
    },
    "mac-lookup": {
      title: "MAC 定位",
      subtitle: "按完整 MAC、前缀或后缀查询并关联设备档案。"
    },
    analysis: {
      title: "网络分析",
      subtitle: "接口、网关、连通性与延迟统计。"
    },
    history: {
      title: "扫描历史",
      subtitle: "查看历史扫描任务与结果变化。"
    },
    settings: {
      title: "系统设置",
      subtitle: "扫描参数、主题、语言与数据存储。"
    }
  };
  var currentRoute = "dashboard";
  var dashboardTimer = null;
  var health = null;

  function tr(value) {
    if (window.NetworkLocatorI18n) {
      return window.NetworkLocatorI18n.t(String(value));
    }
    return String(value);
  }

  function locale() {
    return window.NetworkLocatorI18n
      ? window.NetworkLocatorI18n.locale()
      : "zh";
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function storedTheme() {
    try {
      return window.localStorage.getItem(THEME_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function routeFromHash() {
    var value = String(window.location.hash || "").replace(/^#\/?/, "");
    return Object.prototype.hasOwnProperty.call(ROUTES, value) ? value : "dashboard";
  }

  function setRoute(route, updateHash) {
    var next = Object.prototype.hasOwnProperty.call(ROUTES, route) ? route : "dashboard";
    currentRoute = next;
    var pages = document.querySelectorAll(".v2-page[data-page]");
    for (var index = 0; index < pages.length; index += 1) {
      pages[index].hidden = pages[index].getAttribute("data-page") !== next;
    }
    var navItems = document.querySelectorAll(".v2-nav-item[data-route]");
    for (var itemIndex = 0; itemIndex < navItems.length; itemIndex += 1) {
      var item = navItems[itemIndex];
      var active = item.getAttribute("data-route") === next;
      item.classList.toggle("is-active", active);
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    }
    var title = byId("v2PageTitle");
    var subtitle = byId("v2PageSubtitle");
    if (title) {
      title.textContent = tr(ROUTES[next].title);
    }
    if (subtitle) {
      subtitle.textContent = tr(ROUTES[next].subtitle);
    }
    var content = document.querySelector(".v2-content");
    if (content) {
      content.classList.toggle("is-discovery", next === "discovery");
    }
    if (updateHash !== false) {
      var hash = "#" + next;
      if (window.location.hash !== hash) {
        try {
          window.history.replaceState(null, "", hash);
        } catch (error) {
          window.location.hash = next;
        }
      }
    }
    if (next === "discovery") {
      window.setTimeout(function () {
        if (window.NetworkLocatorApp && typeof window.NetworkLocatorApp.relayoutPanels === "function") {
          window.NetworkLocatorApp.relayoutPanels();
        }
        window.dispatchEvent(new Event("resize"));
      }, 0);
    }
    if (next === "dashboard" && window.NetworkLocatorPages) {
      window.NetworkLocatorPages.refresh("dashboard");
    }
    if (next === "settings") {
      updateSettingsState();
    }
    document.dispatchEvent(new CustomEvent("networklocator:route", {
      detail: { route: next }
    }));
  }

  function startDashboardTimer() {
    stopDashboardTimer();
    dashboardTimer = window.setInterval(function () {
      if (currentRoute === "dashboard" && !document.hidden) {
        updateDashboard();
      }
    }, 3000);
  }

  function stopDashboardTimer() {
    if (dashboardTimer) {
      window.clearInterval(dashboardTimer);
      dashboardTimer = null;
    }
  }

  function appState() {
    return window.NetworkLocatorApp && window.NetworkLocatorApp.state
      ? window.NetworkLocatorApp.state
      : null;
  }

  function renderList(containerId, emptyId, rows) {
    var container = byId(containerId);
    var empty = byId(emptyId);
    if (!container || !empty) {
      return;
    }
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }
    if (!rows.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    rows.forEach(function (row) {
      var line = document.createElement("div");
      line.className = "v2-list-row";
      var strong = document.createElement("strong");
      strong.textContent = row.primary;
      var value = document.createElement("span");
      value.textContent = row.secondary;
      line.appendChild(strong);
      line.appendChild(value);
      container.appendChild(line);
    });
  }

  function updateDashboard() {
    var state = appState();
    var snapshot = window.NetworkLocatorApp && window.NetworkLocatorApp.snapshot
      ? window.NetworkLocatorApp.snapshot()
      : { devices: 0, online: 0, networks: 0, saved: 0 };
    var values = {
      v2StatDevices: snapshot.devices,
      v2StatOnline: snapshot.online,
      v2StatNetworks: snapshot.networks,
      v2StatSaved: snapshot.saved
    };
    Object.keys(values).forEach(function (id) {
      var node = byId(id);
      if (node) {
        node.textContent = String(values[id]);
      }
    });
    var networks = state && Array.isArray(state.networks) ? state.networks : [];
    renderList("v2NetworkList", "v2NetworkEmpty", networks.slice(0, 5).map(function (network) {
      return {
        primary: String(network.interface || "--"),
        secondary: String(network.scan_range || network.local_ip || "")
      };
    }));
    var devices = state && Array.isArray(state.devices) ? state.devices : [];
    renderList("v2RecentList", "v2RecentEmpty", devices.slice(0, 5).map(function (device) {
      return {
        primary: String(device.ip || "--"),
        secondary: String(device.mac || "") + (device.interface ? " · " + device.interface : "")
      };
    }));
  }

  function updateThemeControls() {
    var stored = storedTheme();
    var active = stored === "light" || stored === "dark" || stored === "system"
      ? stored
      : "system";
    var buttons = document.querySelectorAll("[data-theme-choice]");
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].classList.toggle(
        "is-active",
        buttons[index].getAttribute("data-theme-choice") === active
      );
    }
  }

  function updateSettingsState() {
    updateThemeControls();
    var buttons = document.querySelectorAll("[data-locale-choice]");
    for (var index = 0; index < buttons.length; index += 1) {
      buttons[index].classList.toggle(
        "is-active",
        buttons[index].getAttribute("data-locale-choice") === locale()
      );
    }
    var aboutVersion = byId("v2AboutVersion");
    var aboutService = byId("v2AboutService");
    if (aboutVersion && health) {
      aboutVersion.textContent = String(health.version || "--");
    }
    if (aboutService && health) {
      aboutService.textContent = String(health.version || "--");
    }
  }

  function applyThemeChoice(choice) {
    var theme = choice === "dark" ? "dark" : choice === "light" ? "light" : systemTheme();
    if (window.NetworkLocatorApp && typeof window.NetworkLocatorApp.applyTheme === "function") {
      window.NetworkLocatorApp.applyTheme(theme);
    } else {
      document.documentElement.setAttribute("data-theme", theme);
    }
    try {
      window.localStorage.setItem(THEME_KEY, choice);
    } catch (error) {
      /* storage may be blocked */
    }
    updateThemeControls();
  }

  function toggleTheme() {
    var current = document.documentElement.getAttribute("data-theme");
    applyThemeChoice(current === "dark" ? "light" : "dark");
  }

  function toggleLocale() {
    var next = locale() === "en" ? "zh" : "en";
    if (window.NetworkLocatorI18n && window.NetworkLocatorI18n.setLocale(next)) {
      window.location.reload();
    }
  }

  function setLocaleChoice(next) {
    if (window.NetworkLocatorI18n && window.NetworkLocatorI18n.setLocale(next)) {
      window.location.reload();
    }
  }

  function updateLocaleControls() {
    var toggle = byId("v2LocaleToggle");
    if (toggle) {
      toggle.textContent = locale() === "en" ? "中文" : "EN";
      toggle.setAttribute(
        "aria-label",
        locale() === "en" ? "Switch to Chinese" : "Switch to English"
      );
    }
  }

  function apiCandidates() {
    var directory = window.location.pathname.slice(
      0,
      window.location.pathname.lastIndexOf("/") + 1
    );
    var values = [
      "/v2/proxy/" + APP_ID,
      "/v2/proxy/" + APP_ID + "/api",
      directory + "v2/proxy/" + APP_ID
    ];
    var unique = [];
    values.forEach(function (value) {
      if (unique.indexOf(value) < 0) {
        unique.push(value);
      }
    });
    return unique;
  }

  function fetchHealth() {
    var candidates = apiCandidates();
    function attempt(index) {
      if (index >= candidates.length) {
        return Promise.reject(new Error("unavailable"));
      }
      return fetch(candidates[index] + "/health", {
        credentials: "include",
        cache: "no-store"
      }).then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      }).then(function (data) {
        if (data && data.app === APP_ID) {
          return data;
        }
        throw new Error("app mismatch");
      }).catch(function () {
        return attempt(index + 1);
      });
    }
    return attempt(0);
  }

  function updateVersionChrome(data) {
    if (!data) {
      return;
    }
    health = data;
    var version = String(data.version || "--");
    var navVersion = byId("v2NavVersion");
    if (navVersion) {
      navVersion.textContent = "v" + version;
    }
    var aboutVersion = byId("v2AboutVersion");
    var aboutService = byId("v2AboutService");
    if (aboutVersion) {
      aboutVersion.textContent = version;
    }
    if (aboutService) {
      aboutService.textContent = version;
    }
  }

  function bindTheme() {
    var toggle = byId("v2ThemeToggle");
    if (toggle) {
      toggle.addEventListener("click", toggleTheme);
    }
    var choices = document.querySelectorAll("[data-theme-choice]");
    for (var index = 0; index < choices.length; index += 1) {
      choices[index].addEventListener("click", function (event) {
        applyThemeChoice(event.currentTarget.getAttribute("data-theme-choice"));
      });
    }
    window.addEventListener("networklocator:theme", updateThemeControls);
    if (window.matchMedia) {
      var media = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (storedTheme() === "system") {
          applyThemeChoice("system");
        }
      };
      if (typeof media.addEventListener === "function") {
        media.addEventListener("change", onChange);
      } else if (typeof media.addListener === "function") {
        media.addListener(onChange);
      }
    }
  }

  function bindLocale() {
    var toggle = byId("v2LocaleToggle");
    if (toggle) {
      toggle.addEventListener("click", toggleLocale);
    }
    var choices = document.querySelectorAll("[data-locale-choice]");
    for (var index = 0; index < choices.length; index += 1) {
      choices[index].addEventListener("click", function (event) {
        setLocaleChoice(event.currentTarget.getAttribute("data-locale-choice"));
      });
    }
  }

  function bindNavigation() {
    var navItems = document.querySelectorAll(".v2-nav-item[data-route]");
    for (var index = 0; index < navItems.length; index += 1) {
      var item = navItems[index];
      var label = item.querySelector(".v2-nav-label");
      if (label) {
        item.setAttribute("aria-label", label.textContent.trim());
        item.setAttribute("title", label.textContent.trim());
      }
      item.addEventListener("click", function (event) {
        setRoute(event.currentTarget.getAttribute("data-route"));
      });
    }
    var jumps = document.querySelectorAll("[data-route-jump]");
    for (var jumpIndex = 0; jumpIndex < jumps.length; jumpIndex += 1) {
      jumps[jumpIndex].addEventListener("click", function (event) {
        setRoute(event.currentTarget.getAttribute("data-route-jump"));
      });
    }
    window.addEventListener("hashchange", function () {
      setRoute(routeFromHash(), false);
    });
  }

  function bindActions() {
    var scanNow = byId("v2ScanNow");
    if (scanNow) {
      scanNow.addEventListener("click", function () {
        if (
          window.NetworkLocatorPages &&
          typeof window.NetworkLocatorPages.scanInventory === "function"
        ) {
          window.NetworkLocatorPages.scanInventory(scanNow);
          return;
        }
        setRoute("discovery");
        var input = byId("macSuffix");
        if (input) {
          window.setTimeout(function () {
            input.focus();
            input.select();
          }, 40);
        }
      });
    }
    var drawerClose = byId("v2DrawerClose");
    if (drawerClose) {
      drawerClose.addEventListener("click", closeDrawer);
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDrawer();
      }
    });
  }

  function closeDrawer() {
    var drawer = byId("v2Drawer");
    if (drawer && !drawer.hidden) {
      drawer.hidden = true;
    }
  }

  function openDrawer() {
    var drawer = byId("v2Drawer");
    if (drawer) {
      drawer.hidden = false;
      var close = byId("v2DrawerClose");
      if (close) {
        close.focus();
      }
    }
  }

  function init() {
    if (window.NetworkLocatorI18n) {
      window.NetworkLocatorI18n.applyStatic(document.body);
    }
    updateLocaleControls();
    bindNavigation();
    bindTheme();
    bindLocale();
    bindActions();
    updateThemeControls();
    updateSettingsState();
    setRoute(routeFromHash(), false);
    fetchHealth().then(updateVersionChrome).catch(function () {
      updateSettingsState();
    });
    window.NetworkLocatorShell = {
      setRoute: setRoute,
      openDrawer: openDrawer,
      closeDrawer: closeDrawer,
      refreshDashboard: function () {
        if (window.NetworkLocatorPages) {
          window.NetworkLocatorPages.refresh("dashboard");
        }
      }
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}());
