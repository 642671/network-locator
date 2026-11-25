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

    def test_device_inventory_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "v2-pages.js").read_text(encoding="utf-8")
        data = (ROOT / "frontend" / "v2-data.js").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "v2-pages.css").read_text(encoding="utf-8")
        for marker in (
            'id="v2InvFilters"',
            'data-favorite-filter="1"',
            'id="v2InvSearch"',
            'id="v2InvSort"',
            'id="v2InvDirection"',
            'id="v2InvSelectAll"',
            'id="v2InvBulkFavorite"',
            'id="v2InvBulkExport"',
            'id="v2InvExport"',
            'id="v2InvPager"',
            'id="v2InvScan"',
            'id="v2Drawer"',
            'id="v2DrawerNameInput"',
            'id="v2DrawerNoteInput"',
            'id="v2DrawerFavorite"',
            'id="v2DrawerCopyIp"',
            'id="v2DrawerCopyMac"',
            'id="v2DrawerAddresses"',
            'id="v2DrawerIpHistory"',
            'id="v2DrawerEvents"',
            'id="v2MacInput"',
        ):
            self.assertIn(marker, html, marker)
        self.assertLess(html.index('id="v2InvFilters"'), html.index('id="v2InvTableBody"'))
        self.assertLess(html.index('id="v2InvTableBody"'), html.index('id="v2InvPager"'))
        self.assertLess(html.index('data-page="dashboard"'), html.index('data-page="inventory"'))
        combined = script + data
        for marker in (
            "limit: 50",
            "networkLocator.v2.discoveryRanges.v1",
            "v2/devices/scan",
            "v2/scan/start",
            "networklocator:scan-finished",
            "favorite",
            "note",
            "exportDevices",
        ):
            self.assertIn(marker, combined, marker)
        self.assertNotIn("innerHTML = entry.note", script)
        self.assertNotIn("innerHTML = entry.note", (ROOT / "frontend" / "app.js").read_text(encoding="utf-8"))
        for selector in (
            ".v2-drawer",
            ".v2-pager",
            ".v2-bulk-bar",
            ".v2-filter-tabs",
            ".v2-empty-state",
            ".v2-table-wrap",
        ):
            self.assertIn(selector, styles, selector)
        self.assertIn("textContent", script)


    def test_saved_mac_legacy_carryover_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "v2-pages.js").read_text(encoding="utf-8")
        app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        for marker in (
            'id="v2SavedMacsCard"',
            'id="v2SavedMacsCount"',
            'id="v2SavedMacInput"',
            'id="v2SavedMacNote"',
            'id="v2SavedMacAdd"',
            'id="v2SavedMacsList"',
            'id="v2SavedMacsEmpty"',
        ):
            self.assertIn(marker, html, marker)
        for marker in ("readSavedMacs", "persistSavedMacs", "renderSavedMacs"):
            self.assertIn(marker, script, marker)
        self.assertIn("networkLocator.savedMacs.v1", app)
        self.assertIn("SAVED_MACS_LIMIT = 8", app)

    def test_ui_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "frontend" / "v2-pages.js").read_text(encoding="utf-8")
        data = (ROOT / "frontend" / "v2-data.js").read_text(encoding="utf-8")
        server = (ROOT / "backend" / "network_locator" / "server.py").read_text(
            encoding="utf-8"
        )
        v2_api = (ROOT / "backend" / "network_locator" / "v2_api.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="v2ThemeToggle"', html)
        self.assertIn("window.parent.localStorage.getItem(\"themeMode\")", html)
        self.assertIn('data-route="dashboard"', html)
        self.assertIn('data-route="discovery"', html)
        self.assertIn('data-route="inventory"', html)
        self.assertIn('data-route="mac-lookup"', html)
        self.assertIn('data-route="analysis"', html)
        self.assertIn('data-route="history"', html)
        self.assertIn('data-route="settings"', html)
        self.assertIn('id="v2NavVersion"', html)
        self.assertIn('id="v2Drawer"', html)
        self.assertIn('id="v2DiscProgressTrack"', html)
        self.assertIn('id="v2DiscCustom"', html)
        self.assertIn('id="v2DiscPause"', html)
        self.assertIn('id="v2DiscStop"', html)
        self.assertIn('id="v2InvBulkFavorite"', html)
        self.assertIn('id="v2InvBulkExport"', html)
        self.assertIn("networkLocator.theme.v1", html)
        self.assertIn("v2/scan/pause", data)
        self.assertIn("v2/scan/resume", data)
        self.assertIn("v2/scan/stop", data)
        self.assertIn("v2/devices", data)
        self.assertIn("buildDeviceCsv", data)
        self.assertIn("buildResultCsv", data)
        self.assertIn("limit: 50", script)
        self.assertIn("networklocator:scan-finished", script)
        self.assertNotIn("Mock", script)
        self.assertNotIn("mockDevices", script)
        self.assertIn("network-scan", v2_api)
        self.assertIn("devices/scan", server)
        self.assertIn("normalize_mac_suffixes", server)
        self.assertIn("suffixes", server)
        titlebar = html.split('class="titlebar-actions"', 1)[1].split("</header>", 1)[0]
        self.assertNotIn('id="themeToggle"', titlebar)
        self.assertNotIn('id="v2ThemeToggle"', titlebar)
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        shell = (ROOT / "frontend" / "v2-shell.css").read_text(encoding="utf-8")
        self.assertIn("--accent: #2563EB", styles)
        self.assertIn("scrollbar-gutter: stable", styles)
        self.assertIn("--titlebar-height: 41px", styles)
        self.assertIn("--window-frame: 0", styles)
        self.assertIn("--page-bg: #ffffff", styles)
        self.assertIn(".resize-safety-corner", styles)
        self.assertNotIn(".window-resize-grip", styles)
        self.assertIn(".v2-nav", shell)
        self.assertIn(".v2-main", shell)
        self.assertIn(".v2-toolbar", shell)
        self.assertIn("min-width: 0", shell)
        self.assertIn(".v2-page", shell)


    def test_default_window_layout_contract(self) -> None:
        config = json.loads((ROOT / "config.ini").read_text(encoding="utf-8"))
        styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        tokens = (ROOT / "frontend" / "v2-tokens.css").read_text(encoding="utf-8")
        shell = (ROOT / "frontend" / "v2-shell.css").read_text(encoding="utf-8")
        pages = (ROOT / "frontend" / "v2-pages.css").read_text(encoding="utf-8")
        self.assertEqual(config["width"], 1180)
        self.assertEqual(config["height"], 720)
        self.assertTrue(config["resize"])
        self.assertTrue(config["maxmin"])
        self.assertRegex(styles, r"@media\s*\(\s*max-width:\s*980px\s*\)")
        self.assertNotRegex(styles, r"@media\s*\(\s*max-width:\s*1040px\s*\)")
        self.assertIn("--v2-nav-width: 210px", tokens)
        self.assertIn("--v2-toolbar-height: 60px", tokens)
        self.assertIn("--v2-page-padding: 24px", tokens)
        self.assertIn("--v2-drawer-width: 440px", tokens)
        self.assertIn("grid-template-columns: minmax(280px, 0.82fr) minmax(0, 1.6fr)", pages)
        self.assertRegex(pages, r"@media\s*\(\s*max-width:\s*1100px\s*\)")
        self.assertRegex(pages, r"@media\s*\(\s*max-width:\s*820px\s*\)")
        self.assertRegex(pages, r"@media\s*\(\s*max-width:\s*620px\s*\)")
        self.assertIn(".v2-page--discovery", pages)
        self.assertIn("overflow-y: auto", pages)
        self.assertIn("overflow-x: auto", pages)
        self.assertIn(".v2-table-wrap", pages)
        self.assertIn("min-width: 0", pages)
        self.assertIn("min-width: 560px", pages)
        self.assertIn(".v2-frame", shell)
        self.assertIn("height: calc(100vh - var(--titlebar-height))", shell)
        self.assertIn("flex: 0 0 var(--v2-nav-width)", shell)
        self.assertIn(".v2-page", shell)
        self.assertIn("width: 100%", styles)




if __name__ == "__main__":
    unittest.main()
