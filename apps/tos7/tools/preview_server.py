#!/usr/bin/env python3
"""Local WebUI preview with deterministic synthetic TOS API responses."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP_ID = "network-locator"
APP_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
PREVIEW_VERSION = APP_VERSION + "-preview"

# Preview data is synthetic. These strings are sample content, not user data,
# so the preview API swaps them when the browser asks for English. Production
# records are never translated here.
_PREVIEW_EN = {
    "核心网关": "Core gateway",
    "本机 NAS": "Local NAS",
    "客厅 Apple TV": "Living room Apple TV",
    "设计工作站": "Design workstation",
    "Synology 备份机": "Synology backup",
    "访客 iPad": "Guest iPad",
    "智能插座": "Smart plug",
    "临时设备": "Temporary device",
    "Raspberry Pi 网关": "Raspberry Pi gateway",
    "客厅电视柜": "TV cabinet, living room",
    "设计部主力机": "Primary design workstation",
    "每日 02:00 备份": "Daily backup at 02:00",
    "预览示例数据": "Preview sample data",
    "首次发现": "First seen",
    "备注已更新": "Note updated",
    "未知": "Unknown",
    "未知厂商": "Unknown vendor",
    "设备不存在": "Device not found",
    "扫描任务不存在": "Scan task not found",
    "请输入至少一个 MAC 查询": "Enter at least one MAC query",
    "请输入完整的 MAC、前缀或后缀": "Enter a complete MAC, prefix, or suffix",
    "请输入有效的 IPv4 地址或主机名": "Enter a valid IPv4 address or hostname",
    "至少选择一个网段": "Select at least one network",
    "网段选择格式不正确": "Invalid network selection",
    "预览模式会跳过虚拟网卡 docker0": "Preview skips the virtual docker0 interface",
    "预览模式：docker0 已作为虚拟网卡跳过": "Preview: docker0 was skipped as a virtual interface",
    "预览模式：任务与结果为界面示例数据": "Preview: tasks and results are sample UI data",
    "预览模式：设备、统计与扫描历史均为界面示例数据。": "Preview: devices, statistics, and scan history are sample UI data.",
    "预览模式：未执行真实扫描，返回界面示例数据。": "Preview: no real scan ran; sample UI data is returned.",
    "预览模式：接口、DNS 与设备分布均为界面示例数据。": "Preview: interfaces, DNS, and device distribution are sample UI data.",
    "预览模式：自定义范围由示例网段代替，未执行真实扫描。": "Preview: sample networks replace custom ranges; no real scan ran.",
    "示例：目标范围不可达": "Example: the target range is unreachable",
    "所选网段当前不可用，请刷新网段后重试": "The selected networks are unavailable. Refresh and try again.",
    "所选网段当前不可用：": "Selected networks are unavailable: ",
}


def localize_preview(value, lang: str):
    if str(lang or "").lower().startswith("en"):
        if isinstance(value, str):
            if value in _PREVIEW_EN:
                return _PREVIEW_EN[value]
            match = re.match(r"^扫描结果 ([0-9A-F]{4})$", value)
            if match:
                return "Scan result " + match.group(1)
            return value
        if isinstance(value, list):
            return [localize_preview(item, lang) for item in value]
        if isinstance(value, dict):
            return {key: localize_preview(item, lang) for key, item in value.items()}
    return value

NETWORKS = [
    {
        "interface": "enp1s0",
        "network_id": "enp1s0|192.0.2.0/24",
        "alias": "enp1s0",
        "local_ip": "192.0.2.25",
        "prefix_length": 24,
        "gateway": "192.0.2.1",
        "network": "192.0.2.0",
        "broadcast": "192.0.2.255",
        "scan_range": "192.0.2.0/24",
        "host_count": 254,
        "local_source": "192.0.2.25",
        "local_mac": "02-42-AC-11-00-19",
    },
    {
        "interface": "enp2s0",
        "network_id": "enp2s0|198.51.100.0/24",
        "alias": "enp2s0",
        "local_ip": "198.51.100.40",
        "prefix_length": 24,
        "gateway": "198.51.100.1",
        "network": "198.51.100.0",
        "broadcast": "198.51.100.255",
        "scan_range": "198.51.100.0/24",
        "host_count": 254,
        "local_source": "198.51.100.40",
        "local_mac": "02-42-AC-22-00-28",
    },
]

DEVICES = [
    {
        "interface": "enp1s0",
        "scan_range": "192.0.2.0/24",
        "ip": "192.0.2.1",
        "mac": "02-42-AC-11-00-01",
        "state": "REACHABLE",
    },
    {
        "interface": "enp1s0",
        "scan_range": "192.0.2.0/24",
        "ip": "192.0.2.25",
        "mac": "02-42-AC-11-00-19",
        "state": "LOCAL",
    },
    {
        "interface": "enp1s0",
        "scan_range": "192.0.2.0/24",
        "ip": "192.0.2.44",
        "mac": "02-42-AC-11-2C-00",
        "state": "STALE",
    },
    {
        "interface": "enp1s0",
        "scan_range": "192.0.2.0/24",
        "ip": "192.0.2.88",
        "mac": "02-42-AC-11-58-00",
        "state": "DELAY",
    },
    {
        "interface": "enp2s0",
        "scan_range": "198.51.100.0/24",
        "ip": "198.51.100.1",
        "mac": "02-42-AC-22-00-01",
        "state": "REACHABLE",
    },
    {
        "interface": "enp2s0",
        "scan_range": "198.51.100.0/24",
        "ip": "198.51.100.40",
        "mac": "02-42-AC-22-00-28",
        "state": "LOCAL",
    },
    {
        "interface": "enp2s0",
        "scan_range": "198.51.100.0/24",
        "ip": "198.51.100.126",
        "mac": "02-42-AC-22-7E-00",
        "state": "STALE",
    },
]


def network_key(network: dict) -> str:
    return str(
        network.get("network_id")
        or f"{network.get('interface', '')}|{network.get('scan_range', '')}"
    )


def normalize_selected_ids(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("至少选择一个网段")
    selected: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("网段选择格式不正确")
        text = item.strip()
        if text not in selected:
            selected.append(text)
    return selected


def select_preview_networks(
    network_ids: list[str] | None,
) -> tuple[list[dict], list[str]]:
    if network_ids is None:
        return list(NETWORKS), []
    wanted = set(network_ids)
    selected = [network for network in NETWORKS if network_key(network) in wanted]
    available = {network_key(network) for network in NETWORKS}
    missing = [network_id for network_id in network_ids if network_id not in available]
    return selected, missing


class PreviewState:
    def __init__(self, no_match: bool = False) -> None:
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.pause_event = threading.Event()
        self.no_match = no_match
        self.job_sequence = 0
        self.data = self._idle()

    @staticmethod
    def _idle() -> dict:
        return {
            "status": "idle",
            "running": False,
            "stopping": False,
            "paused": False,
            "job_id": "",
            "suffix": "",
            "suffixes": [],
            "selected_network_ids": [],
            "requested_network_ids": None,
            "started_at": None,
            "finished_at": None,
            "networks": [],
            "warnings": ["预览模式会跳过虚拟网卡 docker0"],
            "total_hosts": 0,
            "probed_hosts": 0,
            "progress_percent": 0,
            "current_interface": "",
            "current_range": "",
            "results": [],
            "error": "",
        }

    def status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))

    def start(
        self,
        suffixes: list[str],
        networks: list[dict],
        requested_network_ids: list[str] | None = None,
    ) -> bool:
        with self.lock:
            if self.data["running"]:
                return False
            self.job_sequence += 1
            self.cancel = threading.Event()
            self.pause_event.clear()
            self.data = self._idle()
            self.data.update(
                {
                    "status": "discovering",
                    "running": True,
                    "suffix": suffixes[0],
                    "suffixes": list(suffixes),
                    "selected_network_ids": [network_key(network) for network in networks],
                    "requested_network_ids": (
                        None
                        if requested_network_ids is None
                        else list(requested_network_ids)
                    ),
                    "job_id": f"preview-{self.job_sequence}",
                    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )
        threading.Thread(
            target=self._run,
            args=(list(suffixes), self.cancel, networks),
            daemon=True,
            name="preview-scan",
        ).start()
        return True

    def matches_request(
        self,
        suffixes: list[str],
        network_ids: list[str] | None = None,
    ) -> bool:
        with self.lock:
            if set(self.data["suffixes"]) != set(suffixes):
                return False
            active = self.data.get("requested_network_ids")
            if active is None or network_ids is None:
                return active is None and network_ids is None
            return set(active) == set(network_ids)

    def stop(self) -> None:
        with self.lock:
            self.data["stopping"] = True
            self.data["paused"] = False
        self.pause_event.clear()
        self.cancel.set()

    def pause(self) -> bool:
        with self.lock:
            if not self.data["running"] or self.data["stopping"]:
                return False
            self.pause_event.set()
            self.data["paused"] = True
            self.data["status"] = "paused"
            return True

    def resume(self) -> bool:
        with self.lock:
            if not self.data["running"] or not self.data["paused"]:
                return False
            self.pause_event.clear()
            self.data["paused"] = False
            self.data["status"] = "scanning"
            return True

    def _run(
        self,
        suffixes: list[str],
        cancel: threading.Event,
        networks: list[dict],
    ) -> None:
        time.sleep(0.35)
        if cancel.is_set():
            self._finish("stopped")
            return
        if not networks:
            with self.lock:
                self.data["error"] = "????????"
            self._finish("error")
            return
        total = sum(max(0, int(network.get("host_count") or 0)) for network in networks)
        first = networks[0]
        with self.lock:
            self.data.update(
                {
                    "status": "scanning",
                    "networks": networks,
                    "selected_network_ids": [network_key(network) for network in networks],
                    "total_hosts": total,
                    "current_interface": first["interface"],
                    "current_range": first["scan_range"],
                }
            )
        probed_before = 0
        for network in networks:
            host_count = max(0, int(network.get("host_count") or 0))
            for step in range(1, 5):
                if cancel.is_set():
                    self._finish("stopped")
                    return
                while self.pause_event.is_set() and not cancel.is_set():
                    time.sleep(0.05)
                if cancel.is_set():
                    self._finish("stopped")
                    return
                time.sleep(0.12)
                completed = probed_before + (host_count * step // 4)
                with self.lock:
                    self.data["probed_hosts"] = completed
                    self.data["progress_percent"] = (
                        100 if total <= 0 else int(completed * 100 / total)
                    )
                    self.data["current_interface"] = network["interface"]
                    self.data["current_range"] = network["scan_range"]
            probed_before += host_count
        if not self.no_match:
            network = networks[0]
            local_mac = str(network.get("local_mac") or "02-42-AC-11-00-19")
            local_ip = str(network.get("local_ip") or "192.0.2.25")
            base_ip = local_ip.rsplit(".", 1)[0] + "."
            prefix = local_mac.split("-")[:4]
            results = []
            for index, suffix in enumerate(suffixes):
                suffix_mac = str(suffix).upper()
                results.append(
                    {
                        "interface": network["interface"],
                        "scan_range": network["scan_range"],
                        "ip": base_ip + str(100 + index),
                        "mac": "-".join(prefix + [suffix_mac[:2], suffix_mac[2:]]),
                        "state": "LOCAL",
                        "matched_suffixes": [suffix_mac],
                    }
                )
            with self.lock:
                self.data["results"] = results
        self._finish("completed")

    def _finish(self, status: str) -> None:
        with self.lock:
            self.data.update(
                {
                    "status": status,
                    "running": False,
                    "stopping": False,
                    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "current_interface": "",
                    "current_range": "",
                }
            )
            if status == "completed":
                self.data["progress_percent"] = 100
                self.data["probed_hosts"] = int(self.data.get("total_hosts") or 0)


STATE = PreviewState()


def _v2_iso(minutes_ago: int) -> str:
    return (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


_V2_VENDORS = {
    "3C0754": "Apple",
    "A4C361": "Apple",
    "001B21": "Intel",
    "9009D0": "Synology",
    "24F5A2": "Espressif",
    "B827EB": "Raspberry Pi",
    "0019E0": "TP-Link",
    "005056": "VMware",
}


def _v2_compact(value: object) -> str:
    return "".join(c for c in str(value or "").upper() if c in "0123456789ABCDEF")


def _v2_vendor(mac: object) -> str:
    return _V2_VENDORS.get(_v2_compact(mac)[:6], "")


def _v2_device(
    device_id: str,
    ip: str,
    mac: str,
    name: str,
    interface: str,
    network_id: str,
    status: str,
    minutes_ago: int,
    **extra: object,
) -> dict:
    first = _v2_iso(minutes_ago + 720)
    last = _v2_iso(minutes_ago)
    device = {
        "device_id": device_id,
        "name": name,
        "name_fallback": False,
        "display_name": "",
        "note": "",
        "favorite": False,
        "vendor": _v2_vendor(mac),
        "vendor_known": bool(_v2_vendor(mac)),
        "device_type": "",
        "mac": mac,
        "ip": ip,
        "interface": interface,
        "network_id": network_id,
        "status": status,
        "status_state": "LOCAL" if status == "online" else "STALE" if status == "unknown" else "REACHABLE",
        "status_reason": "预览示例数据",
        "status_reason_code": "preview_sample",
        "status_reason_args": [],
        "random_mac": False,
        "first_seen": first,
        "last_seen": last,
        "last_checked": last,
        "seen_count": 12,
        "search_text": " ".join([name, ip, mac, interface, network_id]),
    }
    device.update(extra)
    device["_base_name"] = name
    addresses = [
        {
            "mac": mac,
            "ip": ip,
            "interface": interface,
            "network_id": network_id,
            "first_seen": first,
            "last_seen": last,
            "is_current": 1,
        }
    ]
    device["addresses"] = addresses
    device["ip_history"] = [
        {
            "ip": ip,
            "macs": [mac],
            "interfaces": [interface],
            "first_seen": first,
            "last_seen": last,
            "is_current": True,
        }
    ]
    device["events"] = [
        {
            "event_id": device_id + "-e1",
            "device_id": device_id,
            "kind": "discovered",
            "detail": "首次发现",
            "detail_code": "discovered",
            "detail_args": [ip, mac],
            "created_at": first,
        }
    ]
    return device


class V2PreviewState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.settings = {
            "scan_timeout_ms": 1200,
            "scan_concurrency": 64,
            "default_interface": "",
            "auto_scan_enabled": False,
            "auto_scan_interval_minutes": 30,
            "stale_after_minutes": 30,
            "csv_delimiter": ",",
            "csv_include_header": True,
            "csv_bom": True,
            "theme": "light",
            "locale": "zh",
            "history_retention_days": 90,
        }
        self.devices = [
            _v2_device("dev-sample-1", "192.0.2.1", "4C-A6-4D-4A-8A-CD", "核心网关", "enp1s0", "enp1s0|192.0.2.0/24", "online", 2),
            _v2_device("dev-sample-2", "192.0.2.25", "02-42-AC-11-00-19", "本机 NAS", "enp1s0", "enp1s0|192.0.2.0/24", "online", 1),
            _v2_device("dev-sample-3", "192.0.2.44", "3C-07-54-9A-1B-2C", "客厅 Apple TV", "enp1s0", "enp1s0|192.0.2.0/24", "online", 4, favorite=True, note="客厅电视柜"),
            _v2_device("dev-sample-4", "192.0.2.88", "00-1B-21-3C-4D-5E", "设计工作站", "enp1s0", "enp1s0|192.0.2.0/24", "online", 6, favorite=True, note="设计部主力机", seen_count=34),
            _v2_device("dev-sample-5", "192.0.2.120", "90-09-D0-11-22-33", "Synology 备份机", "enp1s0", "enp1s0|192.0.2.0/24", "online", 8, note="每日 02:00 备份"),
            _v2_device("dev-sample-6", "198.51.100.10", "A4-C3-61-7E-8F-90", "访客 iPad", "enp2s0", "enp2s0|198.51.100.0/24", "offline", 60 * 30),
            _v2_device("dev-sample-7", "198.51.100.24", "24-F5-A2-AB-CD-EF", "智能插座", "enp2s0", "enp2s0|198.51.100.0/24", "unknown", 95),
            _v2_device("dev-sample-8", "192.0.2.150", "02-11-22-33-44-55", "临时设备", "enp1s0", "enp1s0|192.0.2.0/24", "online", 12, random_mac=True),
            _v2_device("dev-sample-9", "192.0.2.180", "B8-27-EB-12-34-56", "Raspberry Pi 网关", "enp1s0", "enp1s0|192.0.2.0/24", "online", 18),
        ]
        old_ip = "192.0.2.80"
        target = self.devices[3]
        target["ip_history"].append(
            {
                "ip": old_ip,
                "macs": [target["mac"]],
                "interfaces": [target["interface"]],
                "first_seen": _v2_iso(60 * 24 * 6),
                "last_seen": _v2_iso(60 * 24 * 2),
                "is_current": False,
            }
        )
        target["events"].append(
            {
                "event_id": "dev-sample-4-e2",
                "device_id": "dev-sample-4",
                "kind": "ip_changed",
                "detail": old_ip + " → " + target["ip"],
                "detail_code": "ip_changed",
                "detail_args": [old_ip, target["ip"]],
                "created_at": _v2_iso(6),
            }
        )
        target["events"].append(
            {
                "event_id": "dev-sample-4-e3",
                "device_id": "dev-sample-4",
                "kind": "note",
                "detail": "备注已更新",
                "detail_code": "note",
                "detail_args": [],
                "created_at": _v2_iso(120),
            }
        )
        self.tasks = [
            {
                "task_id": "sample-task-3",
                "kind": "inventory",
                "status": "completed",
                "started_at": _v2_iso(8),
                "finished_at": _v2_iso(7),
                "network_ids": ["enp1s0|192.0.2.0/24", "enp2s0|198.51.100.0/24"],
                "networks": [dict(item) for item in NETWORKS],
                "suffixes": [],
                "custom_ranges": [],
                "total_hosts": 508,
                "probed_hosts": 508,
                "discovered": 9,
                "new_devices": 2,
                "offline_devices": 1,
                "ip_changes": 1,
                "result_count": 9,
                "warnings": ["预览模式：任务与结果为界面示例数据"],
                "error": "",
                "results": [
                    {
                        "interface": item["interface"],
                        "scan_range": item["network_id"].split("|", 1)[-1],
                        "ip": item["ip"],
                        "mac": item["mac"],
                        "state": "LOCAL" if item["status"] == "online" else "STALE",
                    }
                    for item in self.devices
                ],
            },
            {
                "task_id": "sample-task-2",
                "kind": "mac",
                "status": "stopped",
                "started_at": _v2_iso(150),
                "finished_at": _v2_iso(148),
                "network_ids": ["enp1s0|192.0.2.0/24"],
                "networks": [dict(NETWORKS[0])],
                "suffixes": ["1B2C", "4D5E"],
                "custom_ranges": [],
                "total_hosts": 254,
                "probed_hosts": 190,
                "discovered": 1,
                "new_devices": 0,
                "offline_devices": 0,
                "ip_changes": 0,
                "result_count": 1,
                "warnings": ["预览模式：任务与结果为界面示例数据"],
                "error": "",
                "results": [
                    {
                        "interface": "enp1s0",
                        "scan_range": "192.0.2.0/24",
                        "ip": "192.0.2.44",
                        "mac": "3C-07-54-9A-1B-2C",
                        "state": "REACHABLE",
                        "matched_suffixes": ["1B2C"],
                    }
                ],
            },
            {
                "task_id": "sample-task-1",
                "kind": "custom",
                "status": "error",
                "started_at": _v2_iso(60 * 24),
                "finished_at": _v2_iso(60 * 24 - 1),
                "network_ids": [],
                "networks": [],
                "suffixes": [],
                "custom_ranges": ["203.0.113.0/28"],
                "total_hosts": 14,
                "probed_hosts": 4,
                "discovered": 0,
                "new_devices": 0,
                "offline_devices": 0,
                "ip_changes": 0,
                "result_count": 0,
                "warnings": [],
                "error": "示例：目标范围不可达",
                "results": [],
            },
        ]

    def _stats(self) -> dict:
        counts = {"online": 0, "offline": 0, "unknown": 0}
        favorites = 0
        networks = set()
        for device in self.devices:
            counts[device["status"]] = counts.get(device["status"], 0) + 1
            if device["favorite"]:
                favorites += 1
            if device["network_id"]:
                networks.add(device["network_id"])
        return {
            "total": len(self.devices),
            "online": counts["online"],
            "offline": counts["offline"],
            "unknown": counts["unknown"],
            "favorites": favorites,
            "networks": len(networks),
            "scans_today": len(self.tasks),
            "last_scan_at": self.tasks[0]["finished_at"] if self.tasks else "",
        }

    def add_bulk_devices(self, count: int) -> None:
        """Generate synthetic devices for pagination and 10k-row UI checks."""

        with self.lock:
            for index in range(max(0, int(count))):
                ip = f"10.99.{index // 254}.{index % 254 + 1}"
                mac = f"02-99-{(index // 65536) % 256:02X}-{(index // 256) % 256:02X}-{index % 256:02X}"
                self.devices.append(
                    _v2_device(
                        f"dev-bulk-{index}",
                        ip,
                        mac,
                        f"Bulk device {index}",
                        "enp1s0",
                        "enp1s0|10.99.0.0/16",
                        "online",
                        index % 240,
                    )
                )

    def _public(self, device: dict) -> dict:
        item = dict(device)
        item.pop("addresses", None)
        item.pop("events", None)
        item.pop("ip_history", None)
        item.pop("_base_name", None)
        return item

    def summary(self) -> dict:
        with self.lock:
            by_network: dict[str, int] = {}
            for device in self.devices:
                key = device.get("network_id") or ""
                by_network[key] = by_network.get(key, 0) + 1
            networks = []
            for item in NETWORKS:
                payload = dict(item)
                payload["device_count"] = by_network.get(item["network_id"], 0)
                networks.append(payload)
            recent = sorted(self.devices, key=lambda item: item["last_seen"], reverse=True)[:6]
            return {
                "ok": True,
                "app": APP_ID,
                "version": PREVIEW_VERSION,
                "sample": True,
                "stats": self._stats(),
                "recent": [self._public(item) for item in recent],
                "networks": networks,
                "warnings": ["预览模式：设备、统计与扫描历史均为界面示例数据。"],
                "settings": dict(self.settings),
                "storage": {
                    "path": "/var/lib/network-locator/preview.sqlite",
                    "directory": "/var/lib/network-locator",
                    "size_bytes": 245760,
                    "writable": True,
                    "sample": True,
                },
                "vendor_count": 205,
                "schema_version": 2,
            }

    def list_devices(self, query: str, status: str, favorite: object, sort: str, direction: str, limit: int, offset: int) -> dict:
        with self.lock:
            items = list(self.devices)
        text = str(query or "").strip().lower()
        if text:
            items = [
                item for item in items
                if text in " ".join(
                    str(item.get(key) or "") for key in (
                        "name", "display_name", "note", "vendor", "mac", "ip", "interface", "network_id"
                    )
                ).lower()
            ]
        if status:
            items = [item for item in items if item.get("status") == status]
        if favorite:
            items = [item for item in items if item.get("favorite")]

        def sort_key(item: dict):
            key = sort or "last_seen"
            if key == "ip":
                return tuple(int(part) if part.isdigit() else 999 for part in str(item.get("ip") or "").split("."))
            if key == "status":
                return {"online": 0, "unknown": 1, "offline": 2}.get(item.get("status"), 3)
            if key == "network":
                return str(item.get("network_id") or "")
            if key in {"name", "mac", "vendor"}:
                return str(item.get(key) or "").lower()
            return str(item.get("last_seen") or "")

        items.sort(key=sort_key, reverse=str(direction or "desc").lower() != "asc")
        total = len(items)
        window = items[max(0, offset): max(0, offset) + max(1, min(5000, limit))]
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "devices": [self._public(item) for item in window],
            "total": total,
            "limit": limit,
            "offset": offset,
            "stats": self._stats(),
            "settings": dict(self.settings),
        }

    def get_device(self, device_id: str):
        with self.lock:
            for item in self.devices:
                if item["device_id"] == device_id:
                    device = dict(item)
                    device.pop("_base_name", None)
                    return device
        return None

    def update_device(self, device_id: str, patch: dict):
        with self.lock:
            for item in self.devices:
                if item["device_id"] != device_id:
                    continue
                if "display_name" in patch:
                    item["display_name"] = str(patch.get("display_name") or "")[:80]
                    item["name_fallback"] = not bool(item["display_name"])
                    item["name"] = item["display_name"] or item.get("_base_name") or "未命名设备"
                if "note" in patch:
                    item["note"] = str(patch.get("note") or "")[:500]
                if "favorite" in patch:
                    item["favorite"] = bool(patch.get("favorite"))
                item.setdefault("events", []).append(
                    {
                        "event_id": device_id + "-e" + str(len(item.get("events") or []) + 1),
                        "device_id": device_id,
                        "kind": "note",
                        "detail": "设备档案已更新",
                        "detail_code": "profile_updated",
                        "detail_args": [],
                        "created_at": _v2_iso(0),
                    }
                )
                device = dict(item)
                device.pop("_base_name", None)
                return device
        return None

    def scan_inventory(self, body: dict) -> dict:
        with self.lock:
            devices = [self._public(item) for item in self.devices]
            stats = self._stats()
        task = {
            "task_id": "sample-live-" + str(int(time.time())),
            "kind": "inventory",
            "status": "completed",
            "started_at": _v2_iso(0),
            "finished_at": _v2_iso(0),
            "network_ids": [item["network_id"] for item in NETWORKS],
            "networks": [dict(item) for item in NETWORKS],
            "suffixes": [],
            "custom_ranges": list(body.get("custom_ranges") or []),
            "total_hosts": 508,
            "probed_hosts": 508,
            "discovered": len(devices),
            "new_devices": 0,
            "offline_devices": stats["offline"],
            "ip_changes": 0,
            "result_count": len(devices),
            "warnings": ["预览模式：未执行真实扫描，返回界面示例数据。"],
            "error": "",
            "results": [],
        }
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "devices": devices,
            "total": len(devices),
            "task": task,
            "warnings": task["warnings"],
            "stats": stats,
        }

    def lookup_mac(self, query: str, mode: str = "auto") -> dict:
        compact = _v2_compact(query)
        if not compact:
            raise ValueError("请输入完整的 MAC、前缀或后缀")
        if mode not in {"auto", "full", "prefix", "suffix", "any"}:
            mode = "auto"
        if mode == "auto":
            if len(compact) == 12:
                mode = "full"
            elif len(compact) == 6:
                mode = "prefix"
            elif len(compact) <= 4:
                mode = "suffix"
            else:
                mode = "any"
        matches = []
        with self.lock:
            for device in self.devices:
                matched = []
                for address in device.get("addresses") or []:
                    mac = _v2_compact(address.get("mac"))
                    if not mac:
                        continue
                    if mode == "full" and mac != compact:
                        continue
                    if mode == "prefix" and not mac.startswith(compact):
                        continue
                    if mode == "suffix" and not mac.endswith(compact):
                        continue
                    if mode == "any" and compact not in mac:
                        continue
                    matched.append(address.get("mac"))
                if matched:
                    item = self._public(device)
                    item["matched_macs"] = matched
                    item["live"] = False
                    matches.append(item)
        vendor_hint = None
        if mode in {"full", "prefix"} and len(compact) >= 6:
            vendor_hint = {"prefix": compact[:6], "vendor": _v2_vendor(compact[:6] + "000000")}
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "query": str(query),
            "mode": mode,
            "hex": compact,
            "vendor_hint": vendor_hint,
            "vendor_prefixes": (
                [{"prefix": compact[:6], "vendor": _v2_vendor(compact[:6] + "000000")}]
                if len(compact) >= 6 and _v2_vendor(compact[:6] + "000000")
                else []
            ),
            "matches": matches,
            "count": len(matches),
        }

    def analysis(self) -> dict:
        with self.lock:
            devices = [self._public(item) for item in self.devices]
            stats = self._stats()
        counts: dict[str, dict[str, int]] = {}
        vendors: dict[str, int] = {}
        for device in devices:
            key = str(device.get("network_id") or "未知")
            bucket = counts.setdefault(key, {"total": 0, "online": 0, "offline": 0, "unknown": 0})
            bucket["total"] += 1
            bucket[device.get("status") or "unknown"] = bucket.get(device.get("status") or "unknown", 0) + 1
            vendor = device.get("vendor") or "未知厂商"
            vendors[vendor] = vendors.get(vendor, 0) + 1
        interfaces = []
        for network in NETWORKS:
            payload = dict(network)
            bucket = counts.get(network["network_id"], {})
            payload["device_count"] = bucket.get("total", 0)
            payload["online_count"] = bucket.get("online", 0)
            interfaces.append(payload)
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "interfaces": interfaces,
            "warnings": ["预览模式：接口、DNS 与设备分布均为界面示例数据。"],
            "dns_servers": ["192.0.2.53", "198.51.100.53"],
            "networks": [
                {"network_id": key, **value} for key, value in sorted(counts.items())
            ],
            "vendors": [
                {"vendor": key, "count": value}
                for key, value in sorted(vendors.items(), key=lambda item: -item[1])[:12]
            ],
            "stats": stats,
            "settings": dict(self.settings),
        }

    def ping(self, body: dict) -> dict:
        host = str(body.get("host") or "").strip()
        if not host and body.get("gateway"):
            host = "192.0.2.1"
        if not host:
            raise ValueError("请输入有效的 IPv4 地址或主机名")
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "host": host,
            "transmitted": int(body.get("count") or 4),
            "received": int(body.get("count") or 4),
            "loss_percent": 0.0,
            "reachable": True,
            "min_ms": 0.42,
            "avg_ms": 1.24,
            "max_ms": 2.86,
            "mdev_ms": 0.31,
            "measured_at": _v2_iso(0),
        }

    def list_tasks(self, limit: int, offset: int) -> dict:
        with self.lock:
            items = [dict(item) for item in self.tasks]
        for item in items:
            item.pop("results", None)
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "tasks": items[offset: offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    def get_task(self, task_id: str):
        with self.lock:
            for item in self.tasks:
                if item["task_id"] == task_id:
                    return dict(item)
        return None

    def purge(self, days: object) -> dict:
        return {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "removed": 0}

    def settings_payload(self) -> dict:
        return {
            "ok": True,
            "app": APP_ID,
            "version": PREVIEW_VERSION,
            "sample": True,
            "settings": dict(self.settings),
            "storage": {
                "path": "/var/lib/network-locator/preview.sqlite",
                "directory": "/var/lib/network-locator",
                "size_bytes": 245760,
                "writable": True,
                "sample": True,
            },
            "vendor_count": 205,
            "schema_version": 2,
            "capabilities": ["store/sqlite", "devices", "scan-history", "mac-lookup", "network-analysis", "custom-ranges", "pause-resume"],
        }

    def update_settings(self, patch: dict) -> dict:
        limits = {
            "scan_timeout_ms": (100, 30000),
            "scan_concurrency": (1, 128),
            "stale_after_minutes": (1, 10080),
            "auto_scan_interval_minutes": (1, 1440),
            "history_retention_days": (1, 3650),
        }
        with self.lock:
            for key, value in patch.items():
                if key not in self.settings:
                    continue
                if key in limits:
                    low, high = limits[key]
                    number = int(value)
                    if number < low or number > high:
                        raise ValueError(key + " 超出范围")
                    self.settings[key] = number
                elif key in {"auto_scan_enabled", "csv_include_header", "csv_bom"}:
                    self.settings[key] = bool(value)
                elif key == "csv_delimiter":
                    text = str(value or "")
                    if text not in {",", ";", "\t"}:
                        raise ValueError("csv_delimiter 必须是逗号、分号或制表符")
                    self.settings[key] = text
                elif key in {"theme", "locale", "default_interface"}:
                    self.settings[key] = str(value or "")
            return dict(self.settings)


V2 = V2PreviewState()


def v2_dispatch(method: str, path: str, body: dict):
    parts = api_parts(path)
    if not parts or parts[0] != "v2":
        return 404, None
    rest = parts[1:]
    values = parse_qs(urlsplit(path).query, keep_blank_values=True)

    def one(key: str, default: str = "") -> str:
        items = values.get(key)
        return items[-1] if items else default

    try:
        if method in {"GET", "HEAD"}:
            if rest == ["summary"]:
                return 200, V2.summary()
            if rest == ["devices"]:
                return 200, V2.list_devices(
                    one("query"),
                    one("status"),
                    one("favorite") in {"1", "true", "yes"},
                    one("sort", "last_seen"),
                    one("direction", "desc"),
                    int(one("limit", "500") or 500),
                    int(one("offset", "0") or 0),
                )
            if len(rest) == 2 and rest[0] == "devices":
                device = V2.get_device(rest[1])
                if device is None:
                    return 404, {"ok": False, "error": "设备不存在"}
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "device": device}
            if rest in (["mac", "lookup"], ["mac"]):
                return 200, V2.lookup_mac(one("q") or one("query"), one("mode", "auto"))
            if rest == ["analysis"]:
                return 200, V2.analysis()
            if rest == ["scans"]:
                return 200, V2.list_tasks(int(one("limit", "50") or 50), int(one("offset", "0") or 0))
            if len(rest) == 2 and rest[0] == "scans":
                task = V2.get_task(rest[1])
                if task is None:
                    return 404, {"ok": False, "error": "扫描任务不存在"}
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "task": task}
            if rest == ["settings"]:
                return 200, V2.settings_payload()
            return 404, None
        if method == "PATCH":
            if len(rest) == 2 and rest[0] == "devices":
                device = V2.update_device(rest[1], body)
                if device is None:
                    return 404, {"ok": False, "error": "设备不存在"}
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "device": device}
            if rest == ["settings"]:
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "settings": V2.update_settings(body)}
            return 404, None
        if method == "POST":
            if rest == ["devices", "scan"]:
                return 200, V2.scan_inventory(body)
            if rest == ["mac", "lookup"]:
                queries = body.get("queries")
                if not isinstance(queries, list) or not queries:
                    return 400, {"ok": False, "error": "请输入至少一个 MAC 查询"}
                results = []
                for query in queries[:100]:
                    text = str(query or "").strip()
                    if not text:
                        continue
                    try:
                        result = V2.lookup_mac(text, "auto")
                        results.append(result)
                    except ValueError as exc:
                        results.append({"query": text, "error": str(exc), "matches": [], "count": 0})
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "results": results}
            if rest == ["analysis", "ping"]:
                return 200, V2.ping(body)
            if rest == ["scans", "purge"]:
                return 200, V2.purge(body.get("older_than_days"))
            if rest == ["settings"]:
                return 200, {"ok": True, "app": APP_ID, "version": PREVIEW_VERSION, "sample": True, "settings": V2.update_settings(body)}
            return 404, None
        return 405, {"ok": False, "error": "method not allowed"}
    except ValueError as exc:
        return 400, {"ok": False, "app": APP_ID, "error": str(exc)}




def api_parts(path: str) -> list[str]:
    parts = [part for part in urlsplit(path).path.split("/") if part]
    while APP_ID in parts:
        index = parts.index(APP_ID)
        del parts[: index + 1]
    if parts and parts[0] == "api":
        parts = parts[1:]
    return parts


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def _json(self, status: int, payload: dict) -> None:
        payload = localize_preview(payload, self.headers.get("Accept-Language", ""))
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        parts = api_parts(self.path)
        if parts == ["health"]:
            self._json(
                200,
                {
                    "ok": True,
                    "status": "ok",
                    "app": APP_ID,
                    "version": PREVIEW_VERSION,
                    "python": "preview",
                    "max_hosts": 1022,
                },
            )
            return
        if parts == ["networks"]:
            self._json(
                200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": PREVIEW_VERSION,
                    "max_hosts": 1022,
                    "networks": NETWORKS,
                    "warnings": ["预览模式：docker0 已作为虚拟网卡跳过"],
                },
            )
            return
        if parts == ["devices"]:
            self._json(
                200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": PREVIEW_VERSION,
                    "devices": DEVICES,
                    "warnings": [],
                },
            )
            return
        if parts == ["scan", "status"]:
            self._json(
                200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": PREVIEW_VERSION,
                    **STATE.status(),
                },
            )
            return
        if parts and parts[0] == "v2":
            status, payload = v2_dispatch("GET", self.path, {})
            if payload is not None:
                self._json(status, payload)
                return
        if self.path.startswith(("/v2/", "/network-locator/")):
            self._json(404, {"ok": False, "error": "not found"})
            return
        if urlsplit(self.path).path in {"", "/"}:
            source = (FRONTEND / "index.html").read_text(encoding="utf-8")
            raw = source.replace("__APP_VERSION__", PREVIEW_VERSION).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return
        super().do_GET()

    def do_POST(self) -> None:
        parts = api_parts(self.path)
        body = self._read_body()
        if parts and parts[0] == "v2":
            status, payload = v2_dispatch("POST", self.path, body)
            if payload is not None:
                self._json(status, payload)
                return
        if parts == ["devices", "scan"]:
            try:
                network_ids = normalize_selected_ids(body.get("network_ids"))
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            networks, missing = select_preview_networks(network_ids)
            if network_ids is not None and not networks:
                self._json(
                    409,
                    {"ok": False, "error": "所选网段当前不可用，请刷新网段后重试"},
                )
                return
            selected_keys = {network_key(network) for network in networks}
            devices = [
                device
                for device in DEVICES
                if f"{device['interface']}|{device['scan_range']}" in selected_keys
            ]
            warnings = (
                ["所选网段当前不可用：" + "、".join(missing)] if missing else []
            )
            self._json(
                200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": PREVIEW_VERSION,
                    "devices": devices,
                    "warnings": warnings,
                },
            )
            return
        if parts == ["scan", "start"]:
            raw_suffixes = body.get("suffixes")
            if raw_suffixes is None:
                legacy = body.get("suffix")
                raw_suffixes = [legacy] if legacy else []
            if not isinstance(raw_suffixes, list) or not raw_suffixes:
                self._json(400, {"ok": False, "error": "invalid suffix"})
                return
            suffixes: list[str] = []
            for item in raw_suffixes:
                text = str(item or "").upper()
                if len(text) != 4 or any(
                    character not in "0123456789ABCDEF" for character in text
                ):
                    self._json(400, {"ok": False, "error": "invalid suffix"})
                    return
                if text not in suffixes:
                    suffixes.append(text)
            custom_ranges = body.get("custom_ranges") or []
            custom_only = bool(body.get("custom_only"))
            custom_note = ""
            if custom_only and isinstance(custom_ranges, list) and custom_ranges:
                network_ids = None
                networks = [NETWORKS[0]]
                missing = []
                custom_note = "预览模式：自定义范围由示例网段代替，未执行真实扫描。"
            else:
                try:
                    network_ids = normalize_selected_ids(body.get("network_ids"))
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                networks, missing = select_preview_networks(network_ids)
                if network_ids is not None and not networks:
                    self._json(
                        409,
                        {"ok": False, "error": "所选网段当前不可用，请刷新网段后重试"},
                    )
                    return
            started = STATE.start(suffixes, networks, network_ids)
            actual = STATE.status()
            if not started and not STATE.matches_request(suffixes, network_ids):
                self._json(
                    409,
                    {
                        "ok": False,
                        "error": "another scan is already running with a different scope",
                    },
                )
                return
            self._json(
                202 if started else 200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "started": started,
                    "running": actual.get("running"),
                    "status": actual.get("status"),
                    "job_id": actual.get("job_id", ""),
                    "suffix": actual.get("suffix", ""),
                    "suffixes": actual.get("suffixes", []),
                    "selected_network_ids": actual.get("selected_network_ids", []),
                    "warnings": [custom_note] if custom_note else [],
                },
            )
            return
        if parts == ["scan", "stop"]:
            STATE.stop()
            self._json(200, {"ok": True, "app": APP_ID, "stopping": True})
            return
        if parts == ["scan", "pause"]:
            started = STATE.pause()
            self._json(
                200 if started else 409,
                {"ok": started, "app": APP_ID, "paused": started, **STATE.status()},
            )
            return
        if parts == ["scan", "resume"]:
            started = STATE.resume()
            self._json(
                200 if started else 409,
                {"ok": started, "app": APP_ID, "paused": not started, **STATE.status()},
            )
            return
        self._json(404, {"ok": False, "error": "not found"})


    def do_PATCH(self) -> None:
        parts = api_parts(self.path)
        body = self._read_body()
        if parts and parts[0] == "v2":
            status, payload = v2_dispatch("PATCH", self.path, body)
            if payload is not None:
                self._json(status, payload)
                return
        self._json(404, {"ok": False, "error": "not found"})


def main() -> int:
    global STATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4178)
    parser.add_argument(
        "--no-match",
        action="store_true",
        help="complete scans without returning a matching device",
    )
    parser.add_argument(
        "--bulk",
        type=int,
        default=0,
        help="append N synthetic devices for large-table checks",
    )
    args = parser.parse_args()
    STATE = PreviewState(no_match=args.no_match)
    if args.bulk > 0:
        V2.add_bulk_devices(args.bulk)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print(f"Preview: http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
