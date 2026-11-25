"""Regression tests for the V2 store, identity rules, history and OUI helpers."""

from __future__ import annotations

import sqlite3
import sys
import threading
import tempfile
import time
import unittest
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from network_locator.core import (  # noqa: E402
    CommandError,
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
    parse_query,
    vendor_count,
    vendor_for_mac,
)
from network_locator.store import SCHEMA_VERSION, Store  # noqa: E402
from network_locator import v2_api  # noqa: E402


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

    def test_scan_task_list_paginates_with_has_more(self) -> None:
        for index in range(3):
            self.store.record_scan_task(
                {
                    "job_id": f"task-page-{index}",
                    "status": "completed",
                    "started_at": f"2026-01-0{index + 1}T10:00:00",
                    "finished_at": f"2026-01-0{index + 1}T10:00:05",
                    "networks": [
                        {
                            "interface": "eth0",
                            "scan_range": "10.0.0.0/24",
                            "network_id": "eth0|10.0.0.0/24",
                        }
                    ],
                    "results": [],
                },
                kind="inventory",
            )
        first = self.store.list_tasks(limit=2, offset=0)
        self.assertEqual(len(first["tasks"]), 2)
        self.assertEqual(first["total"], 3)
        self.assertTrue(first["has_more"])
        second = self.store.list_tasks(limit=2, offset=2)
        self.assertEqual(len(second["tasks"]), 1)
        self.assertFalse(second["has_more"])

    def test_scan_task_detail_paginates_results_and_events(self) -> None:
        results = [
            observation(f"AA-BB-CC-00-{index:02X}-{index:02X}", f"10.0.1.{index + 1}")
            for index in range(60)
        ]
        self.store.record_scan_task(
            {
                "job_id": "task-paged-detail",
                "status": "completed",
                "started_at": "2026-01-01T10:00:00",
                "finished_at": "2026-01-01T10:00:05",
                "networks": [
                    {
                        "interface": "eth0",
                        "scan_range": "10.0.0.0/24",
                        "network_id": "eth0|10.0.0.0/24",
                    }
                ],
                "results": results,
            },
            kind="inventory",
        )
        first = self.store.get_task(
            "task-paged-detail", result_limit=50, result_offset=0,
            event_limit=50, event_offset=0,
        )
        assert first is not None
        self.assertEqual(len(first["results"]), 50)
        self.assertEqual(first["results_total"], 60)
        self.assertTrue(first["results_has_more"])
        self.assertEqual(len(first["events"]), 50)
        self.assertEqual(first["events_total"], 60)
        self.assertTrue(first["events_has_more"])
        self.assertTrue(first["events"][0]["device_name"])
        self.assertEqual(first["events"][0]["detail_code"], "discovered")
        second = self.store.get_task(
            "task-paged-detail", result_limit=50, result_offset=50,
            event_limit=50, event_offset=50,
        )
        assert second is not None
        self.assertEqual(len(second["results"]), 10)
        self.assertFalse(second["results_has_more"])
        self.assertEqual(len(second["events"]), 10)
        self.assertFalse(second["events_has_more"])

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

    def test_mac_lookup_vendor_random_virtual_and_validation(self) -> None:
        self.store.ingest_observations(
            [
                observation("3C-07-54-9A-1B-2C", "192.0.2.44"),
                observation("00-50-56-9A-00-01", "192.0.2.200"),
                observation("02-11-22-33-44-55", "192.0.2.150"),
                observation("4C-A6-4D-4A-8A-CD", "192.0.2.1"),
            ]
        )
        full = self.store.lookup_mac("3c:07:54:9a:1b:2c")
        self.assertEqual(full["mode"], "full")
        self.assertEqual(full["count"], 1)
        self.assertEqual(full["total"], 1)
        vendor = self.store.lookup_mac("Apple")
        self.assertEqual(vendor["mode"], "vendor")
        self.assertEqual(vendor["total"], 1)
        self.assertEqual(vendor["matches"][0]["vendor"], "Apple")
        virtual = self.store.lookup_mac("VMware")
        self.assertEqual(virtual["total"], 1)
        self.assertTrue(virtual["matches"][0]["virtual_adapter"])
        random_mac = self.store.lookup_mac("02-11-22-33-44-55")
        self.assertTrue(random_mac["matches"][0]["random_mac"])
        self.assertEqual(random_mac["matches"][0]["mac_type"], "local")
        unknown = self.store.lookup_mac("4CA64D")
        self.assertEqual(unknown["count"], 1)
        self.assertEqual(unknown["matches"][0]["vendor"], "")
        self.assertFalse(unknown["matches"][0]["vendor_known"])
        self.assertFalse(unknown["vendor_hint"]["vendor_known"])
        for query, mode in (
            ("AA:BB:GG", "auto"),
            ("12345", "auto"),
            ("Acme", "auto"),
            ("3C0754", "full"),
            ("3C07549A", "prefix"),
            ("1B2", "suffix"),
        ):
            with self.assertRaises(ValueError, msg=query):
                self.store.lookup_mac(query, mode)

    def test_mac_lookup_paginates_and_counts_all_matches(self) -> None:
        observations = [
            observation(f"{index:02X}-AA-BB-CC-1B-2C", f"10.1.{index // 200}.{index % 200 + 1}")
            for index in range(120)
        ]
        self.store.ingest_observations(observations)
        first = self.store.lookup_mac("1B2C", "suffix", limit=50, offset=0)
        self.assertEqual(first["count"], 50)
        self.assertEqual(first["total"], 120)
        self.assertTrue(first["has_more"])
        last = self.store.lookup_mac("1B2C", "suffix", limit=50, offset=100)
        self.assertEqual(last["count"], 20)
        self.assertEqual(last["total"], 120)
        self.assertFalse(last["has_more"])
        self.assertEqual({item["device_id"] for item in first["matches"]}.intersection(
            {item["device_id"] for item in last["matches"]}
        ), set())

    def test_mac_lookup_finds_historical_address_and_links_device(self) -> None:
        self.store.ingest_observations([observation("3C-07-54-9A-1B-2C", "192.0.2.44")])
        first = self.store.list_devices()["devices"][0]
        self.store.ingest_observations([observation("AA-BB-CC-DD-EE-FF", "192.0.2.44")])
        second = self.store.list_devices()["devices"]
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["device_id"], first["device_id"])
        historical = self.store.lookup_mac("3C-07-54-9A-1B-2C")
        self.assertEqual(historical["count"], 1)
        self.assertEqual(historical["matches"][0]["device_id"], first["device_id"])
        self.assertIn("3C-07-54-9A-1B-2C", historical["matches"][0]["matched_macs"])


class SettingsAndAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.store = Store(self.root / "network-locator.db")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_storage_relocation_copies_data_and_survives_restart(self) -> None:
        self.store.ingest_observations([observation("AA-BB-CC-11-22-33", "192.0.2.10")])
        self.store.update_settings({"scan_timeout_ms": 2500, "csv_delimiter": ";"})
        original = self.store.path
        target = self.root / "moved"
        info = self.store.relocate_storage(str(target))
        self.assertTrue(info["migrated"])
        self.assertEqual(Path(info["path"]), target / "network-locator.db")
        self.assertEqual(info["directory"], str(target.resolve()))
        self.assertTrue(original.exists())
        self.assertTrue((self.root / "storage-location.json").exists())
        with mock.patch.dict(os.environ, {"APP_DATA": str(self.root)}):
            reopened = Store()
        self.assertEqual(reopened.path, target / "network-locator.db")
        self.assertEqual(reopened.get_settings()["scan_timeout_ms"], 2500)
        self.assertEqual(reopened.get_settings()["csv_delimiter"], ";")
        self.assertEqual(len(reopened.list_devices()["devices"]), 1)
        same = self.store.relocate_storage(str(target))
        self.assertFalse(same["migrated"])

    def test_storage_relocation_rejects_outside_and_existing_target(self) -> None:
        outside = Path(self.tmp.name) / "outside"
        with self.assertRaises(ValueError):
            self.store.relocate_storage(str(outside))
        with self.assertRaises(ValueError):
            self.store.relocate_storage("relative/path")
        target = self.root / "occupied"
        target.mkdir(parents=True)
        (target / "network-locator.db").write_text("not a database", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.relocate_storage(str(target))
        self.assertEqual(self.store.path, self.root / "network-locator.db")

    def test_settings_validation_and_scan_environment(self) -> None:
        settings = self.store.update_settings(
            {
                "scan_timeout_ms": 2400,
                "scan_concurrency": 17,
                "default_interface": "eth1",
                "auto_scan_enabled": "yes",
                "csv_bom": "off",
                "theme": "dark",
                "locale": "en",
            }
        )
        self.assertEqual(settings["scan_timeout_ms"], 2400)
        self.assertEqual(settings["scan_concurrency"], 17)
        self.assertTrue(settings["auto_scan_enabled"])
        self.assertFalse(settings["csv_bom"])
        self.assertEqual(os.environ["SCAN_PING_TIMEOUT_MS"], "2400")
        self.assertEqual(os.environ["SCAN_CONCURRENCY"], "17")
        for patch in (
            {"scan_timeout_ms": True},
            {"scan_timeout_ms": 99},
            {"scan_concurrency": 0},
            {"auto_scan_enabled": "maybe"},
            {"default_interface": "eth 0"},
            {"theme": "sepia"},
            {"locale": "fr"},
        ):
            with self.assertRaises(ValueError, msg=repr(patch)):
                self.store.update_settings(patch)

    def test_default_interface_selection(self) -> None:
        first = target("eth0", local_ip="10.0.0.5")
        second = target("eth1", local_ip="10.1.0.5", gateway="10.1.0.1")
        ids, warnings = v2_api._default_interface_ids([first, second], None, "eth1")
        self.assertEqual(ids, ["eth1|10.0.0.0/24"])
        self.assertEqual(warnings, [])
        ids, warnings = v2_api._default_interface_ids([first, second], None, "eth9")
        self.assertIsNone(ids)
        self.assertTrue(warnings)
        ids, warnings = v2_api._default_interface_ids([first, second], ["kept"], "eth1")
        self.assertEqual(ids, ["kept"])
        self.assertEqual(warnings, [])

    def test_auto_scan_scheduler_runs_from_service_policy(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self) -> float:
                return self.value

        clock = Clock()
        runs: list[int] = []
        manager = SimpleNamespace(status=lambda: {"running": False})
        scheduler = v2_api.AutoScanScheduler(
            self.store,
            manager,
            threading.Lock(),
            runner=lambda: runs.append(1) or {"ok": True},
            clock=clock,
            check_interval_seconds=0.01,
        )
        self.store.update_settings({"auto_scan_enabled": True, "auto_scan_interval_minutes": 30})
        self.assertFalse(scheduler.poll_once(0))
        clock.value = 1799
        self.assertFalse(scheduler.poll_once(1799))
        clock.value = 1800
        self.assertTrue(scheduler.poll_once(1800))
        self.assertEqual(len(runs), 1)
        self.assertTrue(scheduler.status()["last_run_at"])
        self.store.update_settings({"auto_scan_enabled": False})
        clock.value = 5400
        self.assertFalse(scheduler.poll_once(5400))
        self.store.update_settings({"auto_scan_enabled": True})
        self.assertFalse(scheduler.poll_once(5400))
        clock.value = 7200
        self.assertTrue(scheduler.poll_once(7200))
        self.assertEqual(len(runs), 2)

    def test_auto_scan_scheduler_skips_running_and_records_errors(self) -> None:
        class Clock:
            value = 0.0

            def __call__(self) -> float:
                return self.value

        clock = Clock()
        running = {"value": True}
        manager = SimpleNamespace(status=lambda: {"running": running["value"]})
        attempts: list[int] = []

        def runner() -> dict:
            attempts.append(1)
            raise v2_api.V2Error(500, "probe failed")

        scheduler = v2_api.AutoScanScheduler(
            self.store,
            manager,
            threading.Lock(),
            runner=runner,
            clock=clock,
            check_interval_seconds=0.01,
        )
        self.store.update_settings({"auto_scan_enabled": True, "auto_scan_interval_minutes": 30})
        self.assertFalse(scheduler.poll_once(0))
        clock.value = 1800
        self.assertFalse(scheduler.poll_once(1800))
        self.assertEqual(attempts, [])
        running["value"] = False
        clock.value = 3600
        self.assertFalse(scheduler.poll_once(3600))
        self.assertEqual(attempts, [1])
        self.assertIn("probe failed", scheduler.status()["last_error"])


class ScanHistoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "network-locator.sqlite")
        for index in range(3):
            self.store.record_scan_task(
                {
                    "job_id": f"api-task-{index}",
                    "status": "completed",
                    "started_at": f"2026-02-0{index + 1}T10:00:00",
                    "finished_at": f"2026-02-0{index + 1}T10:00:05",
                    "networks": [
                        {
                            "interface": "eth0",
                            "scan_range": "10.0.0.0/24",
                            "network_id": "eth0|10.0.0.0/24",
                        }
                    ],
                    "results": [],
                },
                kind="inventory",
            )
        results = [
            observation(f"AA-BB-CC-11-{index:02X}-{index:02X}", f"10.0.2.{index + 1}")
            for index in range(60)
        ]
        self.store.record_scan_task(
            {
                "job_id": "api-task-detail",
                "status": "completed",
                "started_at": "2026-02-10T10:00:00",
                "finished_at": "2026-02-10T10:00:05",
                "networks": [
                    {
                        "interface": "eth0",
                        "scan_range": "10.0.0.0/24",
                        "network_id": "eth0|10.0.0.0/24",
                    }
                ],
                "results": results,
            },
            kind="inventory",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_route_paginates(self) -> None:
        handler = FakeV2Handler(self.store, path="/v2/scans?limit=2&offset=0")
        v2_api._scans_route(handler, "GET", ["v2", "scans"])
        self.assertEqual(handler.status, 200)
        self.assertEqual(len(handler.payload["tasks"]), 2)
        self.assertEqual(handler.payload["total"], 4)
        self.assertTrue(handler.payload["has_more"])

    def test_detail_route_paginates_results_and_events(self) -> None:
        handler = FakeV2Handler(
            self.store,
            path="/v2/scans/api-task-detail?result_limit=50&result_offset=0"
            "&event_limit=50&event_offset=0",
        )
        v2_api._scans_route(handler, "GET", ["v2", "scans", "api-task-detail"])
        self.assertEqual(handler.status, 200)
        task = handler.payload["task"]
        self.assertEqual(len(task["results"]), 50)
        self.assertEqual(task["results_total"], 60)
        self.assertTrue(task["results_has_more"])
        self.assertEqual(len(task["events"]), 50)
        self.assertEqual(task["events_total"], 60)
        self.assertTrue(task["events_has_more"])

    def test_ping_route_rejects_invalid_input_and_maps_command_errors(self) -> None:
        stats = {
            "host": "192.0.2.1",
            "transmitted": 4,
            "received": 4,
            "loss_percent": 0.0,
            "reachable": True,
            "min_ms": 0.4,
            "avg_ms": 1.2,
            "max_ms": 2.8,
            "mdev_ms": 0.3,
        }
        with mock.patch.object(v2_api, "ping_statistics", return_value=stats):
            handler = FakeV2Handler(self.store, body={"host": "192.0.2.1", "count": 4})
            v2_api._analysis_route(handler, "POST")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.payload["reachable"])

        empty = FakeV2Handler(self.store, body={"host": "", "count": 4})
        with self.assertRaises(v2_api.V2Error) as caught:
            v2_api._analysis_route(empty, "POST")
        self.assertEqual(caught.exception.status, 400)

        bad_count = FakeV2Handler(self.store, body={"host": "192.0.2.1", "count": "x"})
        with self.assertRaises(v2_api.V2Error) as caught:
            v2_api._analysis_route(bad_count, "POST")
        self.assertEqual(caught.exception.status, 400)

        with mock.patch.object(
            v2_api, "ping_statistics", side_effect=CommandError("系统没有可用的 ping 命令")
        ):
            failed = FakeV2Handler(self.store, body={"host": "192.0.2.1"})
            with self.assertRaises(v2_api.V2Error) as caught:
                v2_api._analysis_route(failed, "POST")
        self.assertEqual(caught.exception.status, 503)

    def test_gateway_ping_uses_discovered_default_gateway(self) -> None:
        with mock.patch.object(v2_api, "discover_networks", return_value=([target()], [])), \
                mock.patch.object(
                    v2_api,
                    "ping_statistics",
                    return_value={
                        "host": "10.0.0.1",
                        "transmitted": 4,
                        "received": 4,
                        "loss_percent": 0.0,
                        "reachable": True,
                        "min_ms": 0.1,
                        "avg_ms": 0.2,
                        "max_ms": 0.3,
                        "mdev_ms": 0.0,
                    },
                ) as ping:
            handler = FakeV2Handler(self.store, body={"gateway": True, "count": 4})
            v2_api._analysis_route(handler, "POST")
        self.assertEqual(handler.status, 200)
        ping.assert_called_once_with("10.0.0.1", count=4)


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
        self.assertEqual(classify_query("7549A1B")[0], "invalid")
        self.assertEqual(parse_query("7549A1B", "any")["mode"], "any")
        self.assertEqual(parse_query("Apple")["vendor"]["name"], "Apple")


class FakeV2Handler:
    def __init__(self, store: Store, *, path: str = "/", body: dict | None = None) -> None:
        self.path = path
        self.body = body or {}
        self.command = "POST" if body is not None else "GET"
        self.status = 0
        self.payload: dict = {}
        self.server = SimpleNamespace(store=store, scan_manager=None)

    def _read_json_body(self) -> dict:
        return self.body

    def _send_json(self, status: int, payload: dict, head_only: bool = False) -> None:
        self.status = status
        self.payload = payload


class MacLookupApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "network-locator.sqlite")
        self.store.ingest_observations(
            [
                observation("3C-07-54-9A-1B-2C", "192.0.2.44"),
                observation("02-11-22-33-44-55", "192.0.2.150"),
            ]
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_get_returns_vendor_query_with_paging_fields(self) -> None:
        handler = FakeV2Handler(
            self.store, path="/v2/mac/lookup?q=Apple&mode=auto&limit=10&offset=0"
        )
        v2_api._mac_lookup(handler, "GET")
        self.assertEqual(handler.status, 200)
        self.assertTrue(handler.payload["ok"])
        self.assertEqual(handler.payload["mode"], "vendor")
        self.assertEqual(handler.payload["total"], 1)
        self.assertEqual(handler.payload["limit"], 10)

    def test_batch_reports_per_line_errors_and_match_counts(self) -> None:
        handler = FakeV2Handler(
            self.store,
            body={"queries": ["Apple", "Acme", "1B2C", "AA:BB:GG"], "limit": 50},
        )
        v2_api._mac_lookup(handler, "POST")
        self.assertEqual(handler.status, 200)
        results = handler.payload["results"]
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0]["mode"], "vendor")
        self.assertEqual(results[0]["total"], 1)
        self.assertIn("未收录该厂商", results[1]["error"])
        self.assertEqual(results[2]["total"], 1)
        self.assertIn("MAC 只能包含", results[3]["error"])


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
