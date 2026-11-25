"""Regression tests for the V2 store, identity rules, history and OUI helpers."""

from __future__ import annotations

import sqlite3
import sys
import threading
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from network_locator.core import (  # noqa: E402
    NetworkTarget,
    ScanManager,
    expand_custom_range,
    merge_custom_targets,
    normalize_custom_ranges,
)
from network_locator.oui import (  # noqa: E402
    classify_query,
    mac_kind,
    normalize_mac,
    vendor_count,
    vendor_for_mac,
)
from network_locator.store import SCHEMA_VERSION, Store  # noqa: E402


def observation(mac: str, ip: str, *, state: str = "REACHABLE", scan_range: str = "10.0.0.0/24") -> dict:
    return {
        "mac": mac,
        "ip": ip,
        "interface": "eth0",
        "scan_range": scan_range,
        "state": state,
    }


def target(
    interface: str = "eth0",
    local_ip: str = "10.0.0.5",
    prefix: int = 24,
    gateway: str = "10.0.0.1",
) -> NetworkTarget:
    return NetworkTarget(
        interface=interface,
        alias=interface,
        local_ip=local_ip,
        prefix_length=prefix,
        gateway=gateway,
        network="10.0.0.0",
        broadcast="10.0.0.255",
        scan_range="10.0.0.0/24",
        host_count=254,
        local_source=local_ip,
        local_mac="02-42-AC-00-00-05",
    )


class StoreIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "network-locator.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_mac_with_new_ip_keeps_device_and_history(self) -> None:
        first = self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        self.assertEqual(first["new_devices"], 1)
        device_id = self.store.list_devices()["devices"][0]["device_id"]
        second = self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.20")])
        self.assertEqual(second["new_devices"], 0)
        self.assertEqual(second["ip_changes"], 1)
        devices = self.store.list_devices()["devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], device_id)
        self.assertEqual(devices[0]["ip"], "192.0.2.20")
        detail = self.store.get_device(device_id)
        assert detail is not None
        self.assertEqual([item["ip"] for item in detail["ip_history"]], ["192.0.2.20", "192.0.2.10"])
        self.assertIn("ip_changed", [item["kind"] for item in detail["events"]])

    def test_repeated_scan_updates_one_device(self) -> None:
        for _ in range(3):
            self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        devices = self.store.list_devices()["devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["seen_count"], 3)

    def test_ip_reuse_with_new_mac_is_treated_as_nic_change(self) -> None:
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        self.store.ingest_observations([observation("AA-BB-CC-11-22-44", "192.0.2.10")])
        devices = self.store.list_devices()["devices"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["mac"], "AA-BB-CC-11-22-44")
        detail = self.store.get_device(devices[0]["device_id"])
        assert detail is not None
        self.assertIn("mac_changed", [item["kind"] for item in detail["events"]])

    def test_user_fields_survive_rescan(self) -> None:
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        device_id = self.store.list_devices()["devices"][0]["device_id"]
        self.store.update_device(device_id, {"display_name": "会议室电视", "note": "3F", "favorite": True})
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.30")])
        detail = self.store.get_device(device_id)
        assert detail is not None
        self.assertEqual(detail["name"], "会议室电视")
        self.assertEqual(detail["note"], "3F")
        self.assertTrue(detail["favorite"])
        self.assertEqual(detail["ip"], "192.0.2.30")

    def test_inventory_search_favorite_and_sort(self) -> None:
        self.store.ingest_observations(
            [
                observation("3C-07-54-9A-1B-2C", "192.0.2.44"),
                observation("B8-27-EB-12-34-56", "192.0.2.180"),
                observation("AA-BB-CC-11-22-33", "192.0.2.10"),
            ]
        )
        devices = self.store.list_devices()["devices"]
        apple_id = next(item["device_id"] for item in devices if item["mac"] == "3C-07-54-9A-1B-2C")
        pi_id = next(item["device_id"] for item in devices if item["mac"] == "B8-27-EB-12-34-56")
        self.store.update_device(
            apple_id,
            {"display_name": "客厅 Apple TV", "note": "电视柜", "favorite": True},
        )
        self.store.update_device(pi_id, {"display_name": "树莓派网关"})

        cases = [
            ("客厅", apple_id),
            ("192.0.2.180", pi_id),
            ("B8-27-EB", pi_id),
            ("Apple", apple_id),
            ("电视柜", apple_id),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                result = self.store.list_devices(query=query)["devices"]
                self.assertEqual([item["device_id"] for item in result], [expected])

        favorites = self.store.list_devices(favorite=True)["devices"]
        self.assertEqual([item["device_id"] for item in favorites], [apple_id])

        names = [
            item["name"]
            for item in self.store.list_devices(sort="name", direction="asc")["devices"]
        ]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_inventory_status_filters_stats_and_recent(self) -> None:
        self.store.ingest_observations(
            [
                observation("AA-BB-CC-11-22-33", "192.0.2.10"),
                observation("AA-BB-CC-11-22-44", "192.0.2.11"),
            ],
            complete=True,
            networks=["10.0.0.0/24"],
        )
        self.store.ingest_observations(
            [observation("AA-BB-CC-11-22-33", "192.0.2.10")],
            complete=True,
            networks=["10.0.0.0/24"],
        )
        online = self.store.list_devices(status="online")["devices"]
        offline = self.store.list_devices(status="offline")["devices"]
        self.assertEqual([item["mac"] for item in online], ["AA-BB-CC-11-22-33"])
        self.assertEqual([item["mac"] for item in offline], ["AA-BB-CC-11-22-44"])
        stats = self.store.stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["online"], 1)
        self.assertEqual(stats["offline"], 1)
        self.assertEqual(len(self.store.recent_devices(1)), 1)

    def test_complete_scan_marks_missing_device_offline(self) -> None:
        self.store.ingest_observations(
            [
                observation("AA-BB-CC-11-22-33", "192.0.2.10"),
                observation("AA-BB-CC-11-22-44", "192.0.2.11"),
            ],
            complete=True,
            networks=["10.0.0.0/24"],
        )
        missing_id = [
            item["device_id"]
            for item in self.store.list_devices()["devices"]
            if item["mac"] == "AA-BB-CC-11-22-44"
        ][0]
        summary = self.store.ingest_observations(
            [observation("AA-BB-CC-11-22-33", "192.0.2.10")],
            complete=True,
            networks=["10.0.0.0/24"],
        )
        self.assertEqual(summary["offline_devices"], 1)
        detail = self.store.get_device(missing_id)
        assert detail is not None
        self.assertEqual(detail["status"], "offline")
        self.assertIn("offline", [item["kind"] for item in detail["events"]])

    def test_network_scan_only_marks_missing_offline_when_completed(self) -> None:
        self.store.ingest_observations(
            [
                observation("AA-BB-CC-11-22-33", "192.0.2.10"),
                observation("AA-BB-CC-11-22-44", "192.0.2.11"),
            ]
        )
        base = {
            "networks": [{"scan_range": "10.0.0.0/24"}],
            "results": [observation("AA-BB-CC-11-22-33", "192.0.2.10")],
        }
        stopped = self.store.record_scan_task(
            {"job_id": "net-stopped", "status": "stopped", **base},
            kind="network",
        )
        self.assertEqual(stopped["offline_devices"], 0)
        missing = [
            item
            for item in self.store.list_devices()["devices"]
            if item["mac"] == "AA-BB-CC-11-22-44"
        ][0]
        self.assertNotEqual(missing["status"], "offline")
        completed = self.store.record_scan_task(
            {"job_id": "net-completed", "status": "completed", **base},
            kind="network",
        )
        self.assertEqual(completed["offline_devices"], 1)
        missing = [
            item
            for item in self.store.list_devices()["devices"]
            if item["mac"] == "AA-BB-CC-11-22-44"
        ][0]
        self.assertEqual(missing["status"], "offline")

    def test_stale_online_device_becomes_unknown(self) -> None:
        self.store.update_settings({"stale_after_minutes": 1})
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        with sqlite3.connect(str(self.store.path)) as connection:
            connection.execute("UPDATE devices SET last_checked = ?", ("2000-01-01T00:00:00",))
        devices = self.store.list_devices()["devices"]
        self.assertEqual(devices[0]["status"], "unknown")
        self.assertIn("未检测", devices[0]["status_reason"])

    def test_scan_history_round_trip(self) -> None:
        snapshot = {
            "job_id": "task-test-1",
            "status": "completed",
            "started_at": "2026-01-01T10:00:00",
            "finished_at": "2026-01-01T10:00:07",
            "selected_network_ids": ["eth0|10.0.0.0/24"],
            "networks": [
                {
                    "interface": "eth0",
                    "scan_range": "10.0.0.0/24",
                    "network_id": "eth0|10.0.0.0/24",
                }
            ],
            "suffixes": [],
            "custom_ranges": [],
            "total_hosts": 254,
            "probed_hosts": 254,
            "results": [observation("AA-BB-CC-11-22-33", "192.0.2.10")],
            "warnings": [],
            "error": "",
        }
        task = self.store.record_scan_task(snapshot, kind="inventory")
        self.assertEqual(task["task_id"], "task-test-1")
        self.assertEqual(task["kind"], "inventory")
        self.assertEqual(task["discovered"], 1)
        listing = self.store.list_tasks()
        self.assertEqual(listing["total"], 1)
        self.assertNotIn("results", listing["tasks"][0])
        detail = self.store.get_task("task-test-1")
        assert detail is not None
        self.assertEqual(len(detail["results"]), 1)
        self.assertEqual(self.store.stats()["total"], 1)

    def test_settings_persist_and_validate(self) -> None:
        self.store.update_settings({"scan_timeout_ms": 2500, "scan_concurrency": 24, "csv_delimiter": ";"})
        reopened = Store(self.store.path)
        settings = reopened.get_settings()
        self.assertEqual(settings["scan_timeout_ms"], 2500)
        self.assertEqual(settings["scan_concurrency"], 24)
        self.assertEqual(settings["csv_delimiter"], ";")
        with self.assertRaises(ValueError):
            reopened.update_settings({"scan_timeout_ms": 10})
        with self.assertRaises(ValueError):
            reopened.update_settings({"csv_delimiter": "|"})

    def test_mac_lookup_full_prefix_and_suffix(self) -> None:
        self.store.ingest_observations([observation("3C-07-54-9A-1B-2C", "192.0.2.44")])
        self.assertEqual(self.store.lookup_mac("1B2C", "suffix")["count"], 1)
        self.assertEqual(self.store.lookup_mac("3C0754", "prefix")["count"], 1)
        self.assertEqual(self.store.lookup_mac("3C-07-54-9A-1B-2C", "full")["count"], 1)
        self.assertEqual(self.store.lookup_mac("FFFF", "suffix")["count"], 0)
        self.assertEqual(self.store.list_devices()["devices"][0]["vendor"], "Apple")


class OuiTests(unittest.TestCase):
    def test_normalization(self) -> None:
        self.assertEqual(normalize_mac("aa:bb:cc:dd:ee:f0"), "AA-BB-CC-DD-EE-F0")
        self.assertEqual(normalize_mac("not-a-mac"), "")

    def test_random_and_multicast_detection(self) -> None:
        self.assertEqual(mac_kind("02-11-22-33-44-55"), "local")
        self.assertEqual(mac_kind("01-11-22-33-44-55"), "multicast")
        self.assertEqual(mac_kind("3C-07-54-9A-1B-2C"), "universal")

    def test_vendor_table_is_honest_about_unknowns(self) -> None:
        self.assertEqual(vendor_for_mac("3C-07-54-9A-1B-2C"), "Apple")
        self.assertEqual(vendor_for_mac("4C-A6-4D-4A-8A-CD"), "")
        self.assertGreater(vendor_count(), 100)

    def test_query_classification(self) -> None:
        self.assertEqual(classify_query("3C07549A1B2C")[0], "full")
        self.assertEqual(classify_query("3C0754")[0], "prefix")
        self.assertEqual(classify_query("1B2C")[0], "suffix")
        self.assertEqual(classify_query("7549A1B")[0], "any")


class DataModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "network-locator.sqlite")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_batch_duplicates_are_ignored(self) -> None:
        duplicate = observation("AA-BB-CC-11-22-33", "192.0.2.10")
        summary = self.store.ingest_observations([duplicate, dict(duplicate)])
        self.assertEqual(summary["observed"], 1)
        device = self.store.list_devices()["devices"][0]
        self.assertEqual(device["seen_count"], 1)

    def test_ip_change_keeps_one_device_and_two_address_records(self) -> None:
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        device_id = self.store.list_devices()["devices"][0]["device_id"]
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.20")])
        detail = self.store.get_device(device_id)
        assert detail is not None
        self.assertEqual(len(self.store.list_devices()["devices"]), 1)
        current = [item for item in detail["addresses"] if item["ip"] == "192.0.2.20"]
        history = [item for item in detail["addresses"] if item["ip"] == "192.0.2.10"]
        self.assertEqual(len(current), 1)
        self.assertEqual(len(history), 1)
        self.assertTrue(current[0]["is_current"])
        self.assertFalse(history[0]["is_current"])
        self.assertEqual(detail["status_reason_code"], "online_confirmed")
        event_codes = {item.get("detail_code") for item in detail["events"]}
        self.assertIn("discovered", event_codes)
        self.assertIn("ip_changed", event_codes)

    def test_scan_results_table_links_observation_to_device(self) -> None:
        snapshot = {
            "job_id": "task-results-1",
            "status": "completed",
            "started_at": "2026-01-01T10:00:00",
            "finished_at": "2026-01-01T10:00:07",
            "selected_network_ids": ["eth0|10.0.0.0/24"],
            "networks": [
                {"interface": "eth0", "scan_range": "10.0.0.0/24", "network_id": "eth0|10.0.0.0/24"}
            ],
            "suffixes": [],
            "custom_ranges": [],
            "total_hosts": 254,
            "probed_hosts": 254,
            "results": [observation("AA-BB-CC-11-22-33", "192.0.2.10")],
            "warnings": [],
            "error": "",
        }
        task = self.store.record_scan_task(snapshot, kind="inventory")
        self.assertEqual(task["task_id"], "task-results-1")
        self.assertEqual(len(task["results"]), 1)
        device_id = self.store.list_devices()["devices"][0]["device_id"]
        self.assertEqual(task["results"][0]["device_id"], device_id)
        with sqlite3.connect(str(self.store.path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM scan_results WHERE task_id = ?", ("task-results-1",)
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_network_snapshot_persists_interfaces_and_segments(self) -> None:
        self.store.record_network_snapshot(
            [
                {
                    "interface": "eth0",
                    "alias": "eth0",
                    "local_ip": "10.0.0.5",
                    "prefix_length": 24,
                    "gateway": "10.0.0.1",
                    "network": "10.0.0.0",
                    "broadcast": "10.0.0.255",
                    "scan_range": "10.0.0.0/24",
                    "host_count": 254,
                    "local_mac": "02-42-AC-00-00-05",
                    "network_id": "eth0|10.0.0.0/24",
                }
            ]
        )
        interfaces = self.store.list_interfaces()
        segments = self.store.list_segments()
        self.assertEqual(interfaces[0]["interface"], "eth0")
        self.assertEqual(segments[0]["network_id"], "eth0|10.0.0.0/24")

    def test_ten_thousand_devices_paginate(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        rows = []
        for index in range(10000):
            ip = f"10.0.{index // 254}.{index % 254 + 1}"
            rows.append(
                (
                    f"dev-bulk-{index}",
                    f"Device {index}",
                    "",
                    0,
                    "Example",
                    "",
                    f"02-00-00-{(index // 65536) % 256:02X}-{(index // 256) % 256:02X}-{index % 256:02X}",
                    ip,
                    "eth0",
                    "eth0|10.0.0.0/24",
                    "online",
                    "REACHABLE",
                    0,
                    now,
                    now,
                    now,
                    now,
                    now,
                    1,
                )
            )
        with sqlite3.connect(str(self.store.path)) as connection:
            connection.executemany(
                "INSERT INTO devices("
                "device_id, display_name, note, favorite, vendor, device_type, "
                "mac_current, ip_current, interface_current, network_current, status, "
                "status_state, random_mac, first_seen, last_seen, last_checked, "
                "created_at, updated_at, seen_count"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        page = self.store.list_devices(limit=50, offset=100)
        self.assertEqual(page["total"], 10000)
        self.assertEqual(len(page["devices"]), 50)
        self.assertEqual(self.store.stats()["total"], 10000)
        self.assertEqual(self.store.stats()["online"], 10000)
        self.assertEqual(self.store.network_counts()["eth0|10.0.0.0/24"]["total"], 10000)


class MigrationTests(unittest.TestCase):
    def test_version_one_database_is_upgraded_and_preserved(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "legacy.sqlite"
        with sqlite3.connect(str(path)) as connection:
            connection.executescript(
                """
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE devices (
                    device_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    vendor TEXT NOT NULL DEFAULT '',
                    device_type TEXT NOT NULL DEFAULT '',
                    mac_current TEXT NOT NULL DEFAULT '',
                    ip_current TEXT NOT NULL DEFAULT '',
                    interface_current TEXT NOT NULL DEFAULT '',
                    network_current TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unknown',
                    status_state TEXT NOT NULL DEFAULT '',
                    random_mac INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_checked TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE device_addresses (
                    address_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    mac TEXT NOT NULL,
                    interface TEXT NOT NULL DEFAULT '',
                    network_id TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    last_state TEXT NOT NULL DEFAULT '',
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    is_current INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(device_id, ip, mac, interface)
                );
                CREATE TABLE device_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE scan_tasks (
                    task_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'mac',
                    status TEXT NOT NULL DEFAULT 'completed',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    network_ids TEXT NOT NULL DEFAULT '[]',
                    networks TEXT NOT NULL DEFAULT '[]',
                    suffixes TEXT NOT NULL DEFAULT '[]',
                    custom_ranges TEXT NOT NULL DEFAULT '[]',
                    total_hosts INTEGER NOT NULL DEFAULT 0,
                    probed_hosts INTEGER NOT NULL DEFAULT 0,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    new_devices INTEGER NOT NULL DEFAULT 0,
                    offline_devices INTEGER NOT NULL DEFAULT 0,
                    ip_changes INTEGER NOT NULL DEFAULT 0,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    warnings TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    results TEXT NOT NULL DEFAULT '[]'
                );
                INSERT INTO meta(key, value) VALUES('schema_version', '1');
                INSERT INTO devices(
                    device_id, display_name, note, favorite, vendor, mac_current,
                    ip_current, interface_current, network_current, status,
                    status_state, first_seen, last_seen, last_checked, created_at,
                    updated_at, seen_count
                ) VALUES(
                    'dev-legacy', 'Legacy device', 'keep me', 1, 'Apple',
                    '3C-07-54-9A-1B-2C', '192.0.2.44', 'eth0',
                    'eth0|192.0.2.0/24', 'online', 'REACHABLE',
                    '2026-01-01T10:00:00', '2026-01-01T11:00:00',
                    '2026-01-01T11:00:00', '2026-01-01T10:00:00',
                    '2026-01-01T11:00:00', 4
                );
                INSERT INTO device_addresses(
                    device_id, ip, mac, interface, network_id, first_seen,
                    last_seen, last_state, seen_count, is_current
                ) VALUES(
                    'dev-legacy', '192.0.2.44', '3C-07-54-9A-1B-2C', 'eth0',
                    'eth0|192.0.2.0/24', '2026-01-01T10:00:00',
                    '2026-01-01T11:00:00', 'REACHABLE', 4, 1
                );
                INSERT INTO device_events(device_id, kind, detail, task_id, created_at)
                VALUES('dev-legacy', 'discovered', '首次发现', 'task-legacy', '2026-01-01T10:00:00');
                INSERT INTO scan_tasks(
                    task_id, kind, status, started_at, finished_at, discovered, result_count
                ) VALUES('task-legacy', 'inventory', 'completed',
                         '2026-01-01T10:00:00', '2026-01-01T10:00:07', 1, 1);
                """
            )
        store = Store(path)
        with sqlite3.connect(str(path)) as connection:
            version = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()[0]
            event_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(device_events)")
            }
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(int(version), SCHEMA_VERSION)
        self.assertIn("detail_code", event_columns)
        self.assertIn("detail_args", event_columns)
        self.assertIn("scan_results", tables)
        self.assertIn("network_interfaces", tables)
        self.assertIn("network_segments", tables)
        detail = store.get_device("dev-legacy")
        assert detail is not None
        self.assertEqual(detail["name"], "Legacy device")
        self.assertEqual(detail["note"], "keep me")
        self.assertTrue(detail["favorite"])
        self.assertEqual(detail["status"], "unknown")
        self.assertEqual(detail["status_reason_code"], "stale")
        self.assertEqual(detail["addresses"][0]["ip"], "192.0.2.44")
        self.assertEqual(store.list_tasks()["total"], 1)
        self.assertEqual(store.get_task("task-legacy")["task_id"], "task-legacy")


class CustomRangeTests(unittest.TestCase):
    def test_cidr_and_span_are_normalized(self) -> None:
        self.assertEqual(normalize_custom_ranges(["203.0.113.0/30"]), ["203.0.113.0/30"])
        self.assertEqual(
            normalize_custom_ranges(["192.0.2.10-192.0.2.12"]),
            ["192.0.2.10/31", "192.0.2.12/32"],
        )

    def test_invalid_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            expand_custom_range("192.0.2.20-192.0.2.10")

    def test_custom_targets_borrow_routed_interface(self) -> None:
        merged = merge_custom_targets([target()], ["10.0.0.128/28"])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1].interface, "eth0")
        self.assertEqual(merged[1].scan_range, "10.0.0.128/28")


class PauseResumeTests(unittest.TestCase):
    def test_pause_and_resume_scan(self) -> None:
        release = threading.Event()

        def sweep(item, cancel_event, on_progress, pause_event=None) -> bool:
            on_progress(1)
            while not release.is_set():
                if cancel_event.wait(0.01):
                    return True
            on_progress(item.host_count)
            return True

        manager = ScanManager(
            discover=lambda: ([target()], []),
            neighbors=lambda interface: [],
            sweep=sweep,
        )
        self.assertTrue(manager.start(["1A2B"]))
        deadline = time.time() + 3
        while time.time() < deadline and manager.status()["status"] != "scanning":
            time.sleep(0.01)
        self.assertTrue(manager.pause())
        paused = manager.status()
        self.assertTrue(paused["paused"])
        self.assertEqual(paused["status"], "paused")
        release.set()
        self.assertTrue(manager.resume())
        manager.wait(3)
        final = manager.status()
        self.assertFalse(final["paused"])
        self.assertFalse(final["running"])
        self.assertEqual(final["status"], "completed")

    def test_pause_rejected_when_idle(self) -> None:
        manager = ScanManager(discover=lambda: ([], []))
        self.assertFalse(manager.pause())
        self.assertFalse(manager.resume())


if __name__ == "__main__":
    unittest.main()
