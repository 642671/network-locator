"""Static package-contract checks mirroring the TOS review gate."""

from __future__ import annotations

import configparser
import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PackageContractTests(unittest.TestCase):
    def test_versions_match(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        config = json.loads((ROOT / "config.ini").read_text(encoding="utf-8"))
        control = (ROOT / "DEBIAN" / "control").read_text(encoding="utf-8")
        backend = (ROOT / "backend" / "network_locator" / "__init__.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(config["version"], version)
        self.assertEqual(config["width"], 1180)
        self.assertEqual(config["height"], 720)
        self.assertIn(f"Version: {version}", control)
        self.assertIn(f'__version__ = "{version}"', backend)

    def test_service_contract(self) -> None:
        unit = (ROOT / "init.d" / "networklocator-system.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("User=network-locator", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("Group=network-locator", unit)
        self.assertNotIn("PrivateTmp=true", unit)
        self.assertIn(
            "ExecStart=/usr/bin/python3 "
            "/usr/local/network-locator/bin/network-locator-service",
            unit,
        )

    def test_language_contract(self) -> None:
        wanted = {
            "zh-cn",
            "zh-hk",
            "en-us",
            "fr-fr",
            "de-de",
            "it-it",
            "es-es",
            "hu-hu",
            "ja-jp",
            "ko-kr",
            "pl-pl",
            "ru-ru",
            "tr-tr",
            "pt-pt",
        }
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        raw = (ROOT / "network-locator.lang").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)
        parser.read_string(raw.decode("utf-8"))
        self.assertEqual(set(parser.sections()), wanted)

    def test_language_release_notes_match_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string((ROOT / "network-locator.lang").read_text(encoding="utf-8"))
        for section in parser.sections():
            self.assertTrue(
                parser[section]["release_note"].strip().strip('"').startswith(version),
                section,
            )

    def test_lifecycle_safety_contract(self) -> None:
        for name in ("postinst", "prerm", "postrm"):
            path = ROOT / "DEBIAN" / name
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"#!/bin/sh\n"), name)
            self.assertNotIn(b"\r\n", raw, name)
        postinst = (ROOT / "DEBIAN" / "postinst").read_text(encoding="utf-8")
        postrm = (ROOT / "DEBIAN" / "postrm").read_text(encoding="utf-8")
        self.assertNotIn("chmod 0770 /var/api", postinst)
        self.assertNotIn("apt install", postinst)
        self.assertIn('rm -rf "${APP_DIR}"', postrm)
        self.assertIn("remove|purge", postrm)
        self.assertIn('userdel "${APP_USER}"', postrm)
        control_text = (ROOT / "DEBIAN" / "control").read_text(encoding="utf-8")
        self.assertIn("Depends: python3 (>= 3.10), systemd", control_text)
        self.assertNotIn("iproute2", control_text)
        self.assertNotIn("iputils-ping", control_text)

    def test_preview_uses_package_version(self) -> None:
        preview = (ROOT / "tools" / "preview_server.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = (ROOT / "VERSION")', preview)
        self.assertIn("PREVIEW_VERSION = APP_VERSION", preview)
        self.assertNotRegex(preview, r'"\d+\.\d+\.\d+-preview"')


    def test_privacy_policy_contract(self) -> None:
        config = json.loads((ROOT / "config.ini").read_text(encoding="utf-8"))
        policy = ROOT.parents[1] / "docs" / "PRIVACY.md"
        self.assertTrue(policy.is_file())
        self.assertIn("docs/PRIVACY.md", config["help"])
        body = policy.read_text(encoding="utf-8")
        self.assertIn("does not send", body.lower())
        self.assertIn("/usr/local/network-locator", body)

    def test_release_notes_avoid_forbidden_punctuation(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read_string((ROOT / "network-locator.lang").read_text(encoding="utf-8"))
        for section in parser.sections():
            note = parser[section]["release_note"].strip().strip('"')
            self.assertNotIn(";", note, section)
            self.assertNotIn("#", note, section)

    def test_icon_contract(self) -> None:
        config = json.loads((ROOT / "config.ini").read_text(encoding="utf-8"))
        icon = ROOT / config["icon"].lstrip("/")
        self.assertTrue(icon.is_file())
        self.assertLessEqual(icon.stat().st_size, 50 * 1024)
        root = ET.fromstring(icon.read_bytes())
        self.assertIn("viewBox", root.attrib)
        self.assertIsNone(re.search(r"<script\b", icon.read_text(encoding="utf-8"), re.I))
        full_bleed = next(
            element for element in root if element.tag.rsplit("}", 1)[-1] == "rect"
        )
        self.assertIn(full_bleed.attrib.get("x", "0"), {"0"})
        self.assertIn(full_bleed.attrib.get("y", "0"), {"0"})
        self.assertEqual(full_bleed.attrib.get("width"), "64")
        self.assertEqual(full_bleed.attrib.get("height"), "64")

    def test_saved_devices_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="savedDevicesPanel"', html)
        self.assertIn('id="savedDevicesList"', html)
        self.assertIn('id="savedDeviceDialog"', html)
        self.assertIn('id="savedMacInput"', html)
        self.assertIn('id="savedNoteInput"', html)
        self.assertIn('id="confirmDialog"', html)
        self.assertIn('id="savedDevicesLoadingRow"', html)
        self.assertIn('id="savedDevicesRefreshText"', html)
        self.assertIn('<h2 id="savedDevicesHeading">我的设备</h2>', html)
        self.assertIn('class="workspace-header device-table-header"', html)
        self.assertLess(
            html.index('id="savedDevicesPanel"'),
            html.index('id="tableHeading"')
        )
        self.assertLess(
            html.index('id="tableHeading"'),
            html.index('class="results-surface"')
        )
        self.assertIn("width: max-content", styles)
        self.assertIn(".spinner", styles)
        self.assertIn("progress-slide", styles)
        self.assertIn("networkLocator.savedMacs.v1", script)
        self.assertIn("SAVED_MACS_LIMIT = 8", script)
        self.assertIn("SAVED_NOTE_LIMIT = 100", script)
        self.assertIn("row-select", script)
        self.assertIn("row-action", script)
        self.assertIn("stateLabel", script)
        self.assertIn('id="networkScopeChips"', html)
        self.assertIn('class="select-column"', html)
        self.assertIn('class="actions-column"', html)
        self.assertIn("saved-device-note", script)
        self.assertIn("matchSavedMac", script)
        self.assertIn("mergeSavedMacLastSeen", script)
        self.assertIn("useSavedForSearch", script)
        self.assertNotIn("innerHTML = entry.note", script)
        self.assertIn(".saved-devices", styles)
        self.assertIn(".saved-device-row", styles)
        self.assertIn(".modal-backdrop", styles)

    def test_ui_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        server = (ROOT / "backend" / "network_locator" / "server.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="themeToggle"', html)
        self.assertIn('id="copyIpButton"', html)
        self.assertIn('placeholder="AA-BB / AA:BB / AABB"', html)
        self.assertIn('aria-invalid="false"', html)
        self.assertNotIn('maxlength="5"', html)
        self.assertNotIn('id="inputHint"', html)
        self.assertIn('id="sidebarResizer"', html)
        self.assertIn('id="networkResizer"', html)
        self.assertIn('role="separator"', html)
        self.assertIn('id="tableFilter"', html)
        self.assertIn('data-sort-key="ip"', html)
        self.assertIn("window.parent.localStorage.getItem(\"themeMode\")", html)
        self.assertIn("networkLocator.searchIntent.v1", script)
        self.assertIn("networkLocator.networkSelection.v1", script)
        self.assertIn("networkLocator.networkCache.v1", script)
        self.assertIn("networkLocator.deviceCache.v1", script)
        self.assertIn("verifyCachedNetworks", script)
        self.assertIn("networkVerifying", script)
        self.assertIn("NETWORK_FRESHNESS_MS", script)
        self.assertIn("roundInterrupted", script)
        self.assertNotIn("shell.appendChild(remove)", script)
        self.assertIn("mac-copy", script)
        self.assertIn("macButton.className = \"mac-copy\"", script)
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn(".suffix-input-list.is-multiple", styles)
        self.assertIn(".mac-copy", styles)
        self.assertNotIn(".window-resize-grip", styles)
        self.assertIn(".resize-safety-corner", styles)
        self.assertIn("--accent: #2563EB", styles)
        self.assertNotIn("window-resize-grip", html)
        self.assertIn("resize-safety-corner", html)
        self.assertIn(".field-label-row", styles)
        self.assertIn("scrollbar-gutter: stable", styles)
        self.assertNotRegex(
            styles,
            r"\.field-label-row\s*\{[^}]*position:\s*sticky",
        )
        self.assertNotRegex(
            styles,
            r"\.field-label-row\s*\{[^}]*background:",
        )
        self.assertRegex(
            styles,
            r"\.results-table th\s*\{[^}]*var\(--surface-solid\)",
        )
        self.assertRegex(
            styles,
            r"\.results-table th\s*\{[^}]*background:\s*#f1f5f9\s*;",
        )
        self.assertRegex(
            styles,
            r'html\[data-theme="dark"\] \.results-table th\s*\{[^}]*background:\s*#1e293b\s*;',
        )
        self.assertNotRegex(
            styles,
            r"\.results-table th\s*\{[^}]*background:\s*rgba\(",
        )
        self.assertNotRegex(
            styles,
            r'html\[data-theme="dark"\] \.results-table th\s*\{[^}]*background:\s*rgba\(',
        )
        self.assertRegex(styles, r"--window-frame:\s*0")
        self.assertRegex(styles, r"--page-bg:\s*#ffffff")
        self.assertRegex(
            styles,
            r"\.window-titlebar\s*\{[^}]*left:\s*0",
        )
        self.assertRegex(
            styles,
            r"body\s*\{[^}]*width:\s*100%",
        )
        for block in re.findall(r"\.window-titlebar\s*\{([^}]*)\}", styles):
            top = re.search(r"^\s*top:\s*([^;]+);", block, re.M)
            if top:
                self.assertEqual(top.group(1).strip(), "0")
            right = re.search(r"^\s*right:\s*([^;]+);", block, re.M)
            if right:
                self.assertEqual(right.group(1).strip(), "0")
            left = re.search(r"^\s*left:\s*([^;]+);", block, re.M)
            if left:
                self.assertEqual(left.group(1).strip(), "0")
        self.assertRegex(
            styles,
            r"\.section-heading h1\s*\{[^}]*font-size:\s*13px",
        )
        self.assertRegex(
            styles,
            r"\.section-heading h1\s*\{[^}]*font-weight:\s*650",
        )
        self.assertRegex(
            styles,
            r"\.workspace-heading h2\s*\{[^}]*font-size:\s*12px",
        )
        self.assertRegex(
            styles,
            r"\.workspace-heading h2\s*\{[^}]*font-weight:\s*650",
        )
        def last_heading_decl(selector: str, prop: str) -> str:
            values = []
            for block in re.findall(rf"{selector}\s*\{{([^}}]*)\}}", styles):
                values.extend(
                    value.strip()
                    for value in re.findall(rf"{prop}:\s*([^;]+);", block)
                )
            self.assertTrue(values, selector + " " + prop)
            return values[-1]

        self.assertEqual(last_heading_decl(r"\.section-heading h1", "font-size"), "13px")
        self.assertEqual(last_heading_decl(r"\.section-heading h1", "font-weight"), "650")
        self.assertEqual(last_heading_decl(r"\.workspace-heading h2", "font-size"), "12px")
        self.assertEqual(last_heading_decl(r"\.workspace-heading h2", "font-weight"), "650")
        self.assertIn('id="selectAllNetworksButton"', html)
        self.assertIn("network_ids", script)
        self.assertIn("network_ids", server)
        self.assertIn("resumeContinuousSearch", script)
        self.assertIn("REQUEST_TIMEOUT_MS", script)
        self.assertIn("INVENTORY_REQUEST_TIMEOUT_MS", script)
        self.assertIn("devices/scan", script)
        self.assertIn("inventoryScanning", script)
        self.assertIn('["devices", "scan"]', server)
        self.assertIn('"devices/scan"', server)
        self.assertIn("setInputInvalidState", script)
        self.assertIn("filterTableRows", script)
        self.assertIn("sortTableRows", script)
        self.assertIn("tableFilterSummary", script)
        self.assertIn("var MIN_WORKSPACE_WIDTH = 560", script)
        self.assertIn("var MIN_NETWORK_PANE_HEIGHT = 200", script)
        self.assertIn("当前没有搜索到", script)
        self.assertIn("var MAX_NO_MATCH_ROUNDS = 10", script)
        self.assertIn("轮询查找结束", script)
        self.assertIn("最终没有找到", script)
        self.assertIn("deviceWebUrl", script)
        self.assertIn('target = "_blank"', script)
        self.assertIn('rel = "noopener noreferrer"', script)
        self.assertIn('id="suffixInputList"', html)
        self.assertIn('id="addSuffixButton"', html)
        self.assertLess(
            html.index('id="addSuffixButton"'),
            html.index('id="suffixInputList"')
        )
        self.assertIn('id="targetSummary"', html)
        self.assertIn("var MAX_SUFFIX_INPUTS = 8", script)
        self.assertIn("matched_suffixes", script)
        self.assertIn("normalize_mac_suffixes", server)
        self.assertIn("suffixes", server)
        titlebar = html.split('class="titlebar-actions"', 1)[1].split("</header>", 1)[0]
        self.assertNotIn('id="themeToggle"', titlebar)

    def test_default_window_layout_contract(self) -> None:
        config = json.loads((ROOT / "config.ini").read_text(encoding="utf-8"))
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(config["width"], 1180)
        self.assertEqual(config["height"], 720)
        self.assertTrue(config["resize"])
        self.assertTrue(config["maxmin"])
        self.assertRegex(styles, r"@media\s*\(\s*max-width:\s*980px\s*\)")
        self.assertNotRegex(styles, r"@media\s*\(\s*max-width:\s*1040px\s*\)")
        # The 1180x720 default leaves an 870px workspace, so the full layout
        # with the interface column and per-row actions fits without scrolling.
        self.assertEqual(config["width"], 1180)
        self.assertIn("var WORKSPACE_NARROW_MAX_WIDTH = 680", script)
        self.assertIn(
            "width > 0 && width < WORKSPACE_NARROW_MAX_WIDTH",
            script,
        )
        self.assertNotIn("width < 780", script)
        default_sidebar = 304
        resizer = 6
        min_workspace = 560
        workspace = max(
            min_workspace,
            int(config["width"]) - resizer - default_sidebar,
        )
        self.assertEqual(workspace, 870)
        self.assertGreaterEqual(workspace, 680)
        self.assertRegex(
            styles,
            r"\.workspace\.is-narrow \.results-table\s*\{[^}]*min-width:\s*0",
        )
        self.assertRegex(
            styles,
            r"\.workspace\.is-narrow \.results-table th\.actions-column",
        )
        self.assertRegex(
            styles,
            r"\.workspace\.is-narrow \.results-table td\.actions-cell",
        )
        self.assertIn('class="network-column"', html)
        self.assertIn('data-sort-key="interface"', html)
        self.assertLess(
            html.index('class="network-column"'),
            html.index('data-sort-key="ip"'),
        )
        self.assertIn("network-cell", script)
        self.assertIn("result.interface || \"--\"", script)
        self.assertRegex(
            styles,
            r"\.results-table th\.network-column\s*\{[^}]*width:\s*\d+%",
        )

        def last_decl(selector: str, prop: str) -> str:
            values = []
            for block in re.findall(rf"{selector}\s*\{{([^}}]*)\}}", styles):
                values.extend(
                    value.strip()
                    for value in re.findall(rf"{prop}:\s*([^;]+);", block)
                )
            self.assertTrue(values, selector + " " + prop)
            return values[-1]

        self.assertEqual(last_decl(r"\.workspace-header", "flex-shrink"), "0")
        header_shrink = [
            block
            for block in re.findall(r"\.workspace-header\s*\{([^}]*)\}", styles)
            if re.search(r"flex-shrink:\s*0", block)
        ]
        self.assertGreaterEqual(len(header_shrink), 3)
        self.assertIsNone(re.search(r"\.table-filter\s*\{[^}]*flex-basis:\s*340px", styles))
        self.assertRegex(
            styles,
            r"\.table-filter\s*\{[^}]*flex:\s*1 1 220px",
        )
        self.assertRegex(
            styles,
            r"\.table-filter\s*\{[^}]*min-width:\s*0",
        )
        self.assertRegex(
            styles,
            r"\.workspace\.is-narrow \.table-filter\s*\{[^}]*flex:\s*1 1 200px",
        )
        self.assertRegex(
            styles,
            r"\.table-toolbar\s*\{[^}]*flex-wrap:\s*wrap",
        )
        self.assertRegex(
            styles,
            r"\.workspace\.is-narrow \.table-toolbar\s*\{[^}]*flex-wrap:\s*wrap",
        )




if __name__ == "__main__":
    unittest.main()
