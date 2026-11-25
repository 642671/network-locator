"""Persistent inventory, scan history and settings for Network Locator V2.

The original application kept every piece of state in browser localStorage.
V2 adds a small SQLite database under ``APP_DATA`` (``/usr/local/network-locator/data``
in the package) while keeping every legacy scan API unchanged.

Design rules implemented here:

* ``device_id`` is generated and stable. IP and MAC are never used as identity.
* A device is matched by MAC first, then by an IP + interface seen recently
  (this keeps a device together when a random MAC changes).
* User supplied name / note / favorite are only changed by explicit API calls,
  never by a scan.
* Online / offline / unknown are derived with documented rules, not guessed.
* Every scan task and every device change is recorded for the history page.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .oui import mac_kind, normalize_mac, vendor_for_mac

SCHEMA_VERSION = 1
APP_ID = "network-locator"

ONLINE_STATES = {"LOCAL", "REACHABLE"}
NEIGHBOR_STATES = {"DELAY", "STALE", "PROBE"}
VALID_STATES = ONLINE_STATES | NEIGHBOR_STATES
STATUS_VALUES = {"online", "offline", "unknown"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "scan_timeout_ms": 1000,
    "scan_concurrency": 64,
    "default_interface": "",
    "auto_scan_enabled": False,
    "auto_scan_interval_minutes": 30,
    "stale_after_minutes": 60,
    "csv_delimiter": ",",
    "csv_include_header": True,
    "csv_bom": True,
    "theme": "light",
    "locale": "zh",
    "history_retention_days": 90,
}

_SETTINGS_LIMITS = {
    "scan_timeout_ms": (100, 30000),
    "scan_concurrency": (1, 128),
    "auto_scan_interval_minutes": (1, 1440),
    "stale_after_minutes": (1, 10080),
    "history_retention_days": (1, 3650),
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def default_data_dir() -> Path:
    configured = str(os.environ.get("APP_DATA") or "").strip()
    if configured:
        return Path(configured)
    # backend/network_locator/store.py -> backend/data in a source checkout,
    # /usr/local/network-locator/data in the installed package.
    return Path(__file__).resolve().parents[2] / "data"


def _compact(value: object) -> str:
    text = str(value or "").upper()
    return "".join(character for character in text if character in "0123456789ABCDEF")


def _device_label(row: Mapping[str, Any]) -> str:
    name = str(row.get("display_name") or "").strip()
    if name:
        return name
    vendor = str(row.get("vendor") or "").strip()
    mac = str(row.get("mac_current") or "")
    suffix = mac.replace("-", "")[-4:] if mac else ""
    if vendor and suffix:
        return f"{vendor} {suffix}"
    if vendor:
        return vendor
    return "未命名设备"


def _status_reason(status: str, state: str, checked: datetime | None, stale_minutes: int) -> str:
    if status == "offline":
        return "最近一次完整扫描未发现该设备"
    if state in NEIGHBOR_STATES:
        return "邻居表中存在，但最近一次探测未确认可达"
    if status == "online":
        return "最近一次扫描确认在线"
    if checked is None:
        return "尚未检测"
    age_minutes = int((datetime.now() - checked).total_seconds() // 60)
    if age_minutes > stale_minutes:
        return f"超过 {stale_minutes} 分钟未检测"
    return "尚无明确结果"


def _effective_status(row: Mapping[str, Any], stale_minutes: int) -> str:
    row = dict(row)
    status = str(row.get("status") or "unknown")
    if status not in STATUS_VALUES:
        status = "unknown"
    if status == "online":
        checked = _parse_time(row.get("last_checked"))
        if checked is None:
            return "unknown"
        if datetime.now() - checked > timedelta(minutes=stale_minutes):
            return "unknown"
    return status


class Store:
    """Thread-safe SQLite store used by the HTTP handlers and scan worker."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        if path is None:
            data_dir = default_data_dir()
            self.path = data_dir / f"{APP_ID}.db"
        else:
            self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    # ---------------------------------------------------------------- schema
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 8000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
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
                CREATE TABLE IF NOT EXISTS device_addresses (
                    address_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
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
                CREATE TABLE IF NOT EXISTS device_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scan_tasks (
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
                CREATE INDEX IF NOT EXISTS idx_address_device ON device_addresses(device_id);
                CREATE INDEX IF NOT EXISTS idx_address_mac ON device_addresses(mac);
                CREATE INDEX IF NOT EXISTS idx_address_ip ON device_addresses(ip, interface);
                CREATE INDEX IF NOT EXISTS idx_events_device ON device_events(device_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_time ON scan_tasks(finished_at);
                CREATE INDEX IF NOT EXISTS idx_devices_network ON devices(network_current);
                CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
                """
            )
            current = connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if current is None:
                connection.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            # Future migrations compare the stored version and upgrade step by
            # step. Version 1 is the initial V2 schema.

    # -------------------------------------------------------------- settings
    def get_settings(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'settings'"
            ).fetchone()
        stored: dict[str, Any] = {}
        if row is not None:
            try:
                parsed = json.loads(row["value"])
                if isinstance(parsed, dict):
                    stored = parsed
            except (TypeError, ValueError):
                stored = {}
        settings = dict(DEFAULT_SETTINGS)
        settings.update({key: stored[key] for key in DEFAULT_SETTINGS if key in stored})
        self._apply_scan_environment(settings)
        return settings

    def update_settings(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, Mapping):
            raise ValueError("settings must be an object")
        current = self.get_settings()
        for key, value in patch.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if key in _SETTINGS_LIMITS:
                try:
                    number = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be a number") from exc
                low, high = _SETTINGS_LIMITS[key]
                if number < low or number > high:
                    raise ValueError(f"{key} must be between {low} and {high}")
                current[key] = number
            elif key in {"auto_scan_enabled", "csv_include_header", "csv_bom"}:
                current[key] = bool(value)
            elif key == "csv_delimiter":
                text = str(value or "")
                if text not in {",", ";", "\t"}:
                    raise ValueError("csv_delimiter must be comma, semicolon or tab")
                current[key] = text
            elif key == "theme":
                text = str(value or "")
                if text not in {"light", "dark", "system"}:
                    raise ValueError("theme must be light, dark or system")
                current[key] = text
            elif key == "locale":
                text = str(value or "")
                if text not in {"zh", "en"}:
                    raise ValueError("locale must be zh or en")
                current[key] = text
            elif key == "default_interface":
                current[key] = str(value or "")[:64]
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO meta(key, value) VALUES('settings', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps(current, ensure_ascii=False),),
            )
        self._apply_scan_environment(current)
        return current

    @staticmethod
    def _apply_scan_environment(settings: Mapping[str, Any]) -> None:
        os.environ["SCAN_PING_TIMEOUT_MS"] = str(settings["scan_timeout_ms"])
        os.environ["SCAN_CONCURRENCY"] = str(settings["scan_concurrency"])

    def storage_info(self) -> dict[str, Any]:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return {
            "path": str(self.path),
            "directory": str(self.path.parent),
            "size_bytes": size,
            "writable": os.access(str(self.path.parent), os.W_OK),
        }

    # --------------------------------------------------------------- devices
    def _find_device_by_mac(self, connection: sqlite3.Connection, mac: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT d.* FROM devices d "
            "JOIN device_addresses a ON a.device_id = d.device_id "
            "WHERE a.mac = ? ORDER BY a.last_seen DESC LIMIT 1",
            (mac,),
        ).fetchone()

    def _find_device_by_ip(
        self,
        connection: sqlite3.Connection,
        ip: str,
        interface: str,
        now: datetime,
    ) -> sqlite3.Row | None:
        cutoff = (now - timedelta(days=7)).isoformat(timespec="seconds")
        if interface:
            return connection.execute(
                "SELECT d.* FROM devices d "
                "JOIN device_addresses a ON a.device_id = d.device_id "
                "WHERE a.ip = ? AND a.interface = ? AND a.last_seen >= ? "
                "ORDER BY a.last_seen DESC LIMIT 1",
                (ip, interface, cutoff),
            ).fetchone()
        return connection.execute(
            "SELECT d.* FROM devices d "
            "JOIN device_addresses a ON a.device_id = d.device_id "
            "WHERE a.ip = ? AND a.last_seen >= ? "
            "ORDER BY a.last_seen DESC LIMIT 1",
            (ip, cutoff),
        ).fetchone()

    def _create_device(
        self,
        connection: sqlite3.Connection,
        *,
        mac: str,
        ip: str,
        interface: str,
        network_id: str,
        state: str,
        now_text: str,
    ) -> sqlite3.Row:
        device_id = "dev_" + uuid.uuid4().hex
        vendor = vendor_for_mac(mac)
        random_mac = 1 if mac_kind(mac) == "local" else 0
        status = "online" if state in ONLINE_STATES else "unknown"
        connection.execute(
            "INSERT INTO devices("
            "device_id, display_name, note, favorite, vendor, device_type, "
            "mac_current, ip_current, interface_current, network_current, "
            "status, status_state, random_mac, first_seen, last_seen, "
            "last_checked, created_at, updated_at, seen_count"
            ") VALUES (?, '', '', 0, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                device_id,
                vendor,
                mac,
                ip,
                interface,
                network_id,
                status,
                state,
                random_mac,
                now_text,
                now_text,
                now_text,
                now_text,
                now_text,
            ),
        )
        return connection.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()

    def _event(
        self,
        connection: sqlite3.Connection,
        device_id: str,
        kind: str,
        detail: str,
        task_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            "INSERT INTO device_events(device_id, kind, detail, task_id, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (device_id, kind, detail, task_id, created_at),
        )

    def _upsert_address(
        self,
        connection: sqlite3.Connection,
        *,
        device_id: str,
        ip: str,
        mac: str,
        interface: str,
        network_id: str,
        state: str,
        now_text: str,
    ) -> None:
        connection.execute(
            "UPDATE device_addresses SET is_current = 0 "
            "WHERE device_id = ? AND interface = ? AND (ip <> ? OR mac <> ?)",
            (device_id, interface, ip, mac),
        )
        connection.execute(
            "INSERT INTO device_addresses("
            "device_id, ip, mac, interface, network_id, first_seen, last_seen, "
            "last_state, seen_count, is_current"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, 1) "
            "ON CONFLICT(device_id, ip, mac, interface) DO UPDATE SET "
            "last_seen = excluded.last_seen, last_state = excluded.last_state, "
            "seen_count = device_addresses.seen_count + 1, is_current = 1, "
            "network_id = excluded.network_id",
            (device_id, ip, mac, interface, network_id, now_text, now_text, state),
        )
    def ingest_observations(
        self,
        observations: Iterable[Mapping[str, Any]],
        *,
        task_id: str = "",
        complete: bool = False,
        networks: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Persist scan observations and return a change summary."""

        now = datetime.now()
        now_text = now.isoformat(timespec="seconds")
        observed_ids: set[str] = set()
        summary = {
            "observed": 0,
            "new_devices": 0,
            "ip_changes": 0,
            "mac_changes": 0,
            "offline_devices": 0,
            "online_devices": 0,
        }
        network_list = [str(item) for item in (networks or []) if str(item)]
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for item in observations:
                    if not isinstance(item, Mapping):
                        continue
                    mac = normalize_mac(item.get("mac"))
                    ip = str(item.get("ip") or "").strip()
                    if not mac or not ip:
                        continue
                    interface = str(item.get("interface") or "")
                    network_id = str(item.get("scan_range") or item.get("network_id") or "")
                    state = str(item.get("state") or "").upper()
                    if state not in VALID_STATES:
                        state = ""
                    device = self._find_device_by_mac(connection, mac)
                    if device is None:
                        device = self._find_device_by_ip(connection, ip, interface, now)
                    if device is None:
                        device = self._create_device(
                            connection,
                            mac=mac,
                            ip=ip,
                            interface=interface,
                            network_id=network_id,
                            state=state,
                            now_text=now_text,
                        )
                        summary["new_devices"] += 1
                        self._event(
                            connection,
                            device["device_id"],
                            "discovered",
                            f"{ip} · {mac}",
                            task_id,
                            now_text,
                        )
                    device_id = str(device["device_id"])
                    previous_ip = str(device["ip_current"] or "")
                    previous_mac = str(device["mac_current"] or "")
                    previous_status = str(device["status"] or "unknown")
                    if previous_ip and previous_ip != ip:
                        self._event(
                            connection,
                            device_id,
                            "ip_changed",
                            f"{previous_ip} → {ip}",
                            task_id,
                            now_text,
                        )
                        summary["ip_changes"] += 1
                    if previous_mac and previous_mac != mac:
                        self._event(
                            connection,
                            device_id,
                            "mac_changed",
                            f"{previous_mac} → {mac}",
                            task_id,
                            now_text,
                        )
                        summary["mac_changes"] += 1
                    status = "online" if state in ONLINE_STATES else "unknown"
                    if status == "online" and previous_status == "offline":
                        self._event(
                            connection,
                            device_id,
                            "online",
                            f"{ip} 重新上线",
                            task_id,
                            now_text,
                        )
                    if status == "online":
                        summary["online_devices"] += 1
                    self._upsert_address(
                        connection,
                        device_id=device_id,
                        ip=ip,
                        mac=mac,
                        interface=interface,
                        network_id=network_id,
                        state=state,
                        now_text=now_text,
                    )
                    connection.execute(
                        "UPDATE devices SET "
                        "mac_current = ?, ip_current = ?, interface_current = ?, "
                        "network_current = ?, status = ?, status_state = ?, "
                        "vendor = ?, random_mac = ?, last_seen = ?, last_checked = ?, "
                        "updated_at = ?, seen_count = seen_count + 1 "
                        "WHERE device_id = ?",
                        (
                            mac,
                            ip,
                            interface,
                            network_id,
                            status,
                            state,
                            vendor_for_mac(mac),
                            1 if mac_kind(mac) == "local" else 0,
                            now_text,
                            now_text,
                            now_text,
                            device_id,
                        ),
                    )
                    observed_ids.add(device_id)
                    summary["observed"] += 1

                if complete and network_list:
                    placeholders = ",".join("?" for _ in network_list)
                    rows = connection.execute(
                        "SELECT * FROM devices WHERE status IN ('online','unknown') "
                        f"AND network_current IN ({placeholders})",
                        tuple(network_list),
                    ).fetchall()
                    for row in rows:
                        if str(row["device_id"]) in observed_ids:
                            continue
                        connection.execute(
                            "UPDATE devices SET status = 'offline', status_state = '', "
                            "last_checked = ?, updated_at = ? WHERE device_id = ?",
                            (now_text, now_text, row["device_id"]),
                        )
                        self._event(
                            connection,
                            str(row["device_id"]),
                            "offline",
                            "完整扫描中未发现",
                            task_id,
                            now_text,
                        )
                        summary["offline_devices"] += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return summary

    def list_devices(
        self,
        *,
        query: str = "",
        status: str = "",
        favorite: bool | None = None,
        sort: str = "last_seen",
        direction: str = "desc",
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        settings = self.get_settings()
        stale_minutes = int(settings["stale_after_minutes"])
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM devices").fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            effective = _effective_status(row, stale_minutes)
            items.append(self._device_summary(row, effective, stale_minutes))
        needle = str(query or "").strip().lower()
        if needle:
            items = [item for item in items if needle in str(item["search_text"]).lower()]
        if status in STATUS_VALUES:
            items = [item for item in items if item["status"] == status]
        if favorite is not None:
            items = [item for item in items if bool(item["favorite"]) == bool(favorite)]
        items.sort(key=lambda item: self._sort_key(item, sort), reverse=direction != "asc")
        total = len(items)
        safe_limit = max(1, min(5000, int(limit)))
        safe_offset = max(0, int(offset))
        return {
            "devices": items[safe_offset : safe_offset + safe_limit],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    @staticmethod
    def _sort_key(item: Mapping[str, Any], sort: str) -> Any:
        if sort == "ip":
            return _ip_sort_value(str(item.get("ip") or ""))
        if sort == "mac":
            return str(item.get("mac") or "")
        if sort == "name":
            return str(item.get("name") or "").lower()
        if sort == "vendor":
            return str(item.get("vendor") or "").lower()
        if sort == "status":
            return {"online": 0, "unknown": 1, "offline": 2}.get(str(item.get("status")), 3)
        if sort == "first_seen":
            return str(item.get("first_seen") or "")
        if sort == "network":
            return str(item.get("network_id") or "")
        return str(item.get("last_seen") or "")

    def _device_summary(
        self,
        row: Mapping[str, Any],
        status: str,
        stale_minutes: int,
    ) -> dict[str, Any]:
        row = dict(row)
        checked = _parse_time(row.get("last_checked"))
        vendor = str(row.get("vendor") or "")
        search_parts = (
            _device_label(row),
            row.get("display_name"),
            row.get("note"),
            row.get("vendor"),
            row.get("mac_current"),
            row.get("ip_current"),
            row.get("interface_current"),
            row.get("network_current"),
        )
        return {
            "device_id": row["device_id"],
            "name": _device_label(row),
            "display_name": row.get("display_name") or "",
            "note": row.get("note") or "",
            "favorite": bool(row.get("favorite")),
            "vendor": vendor,
            "vendor_known": bool(vendor),
            "device_type": row.get("device_type") or "",
            "mac": row.get("mac_current") or "",
            "ip": row.get("ip_current") or "",
            "interface": row.get("interface_current") or "",
            "network_id": row.get("network_current") or "",
            "status": status,
            "status_state": row.get("status_state") or "",
            "status_reason": _status_reason(status, str(row.get("status_state") or ""), checked, stale_minutes),
            "random_mac": bool(row.get("random_mac")),
            "first_seen": row.get("first_seen") or "",
            "last_seen": row.get("last_seen") or "",
            "last_checked": row.get("last_checked") or "",
            "seen_count": int(row.get("seen_count") or 0),
            "search_text": " ".join(str(part or "") for part in search_parts),
        }

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        settings = self.get_settings()
        stale_minutes = int(settings["stale_after_minutes"])
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None:
                return None
            addresses = connection.execute(
                "SELECT * FROM device_addresses WHERE device_id = ? "
                "ORDER BY is_current DESC, last_seen DESC",
                (device_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM device_events WHERE device_id = ? "
                "ORDER BY created_at DESC, event_id DESC LIMIT 100",
                (device_id,),
            ).fetchall()
        effective = _effective_status(row, stale_minutes)
        detail = self._device_summary(row, effective, stale_minutes)
        detail["addresses"] = [dict(item) for item in addresses]
        detail["events"] = [dict(item) for item in events]
        detail["ip_history"] = self._ip_history(detail["addresses"])
        return detail

    @staticmethod
    def _ip_history(addresses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for address in addresses:
            ip = str(address.get("ip") or "")
            if not ip:
                continue
            entry = grouped.get(ip)
            if entry is None:
                entry = {
                    "ip": ip,
                    "macs": [],
                    "interfaces": [],
                    "first_seen": address.get("first_seen"),
                    "last_seen": address.get("last_seen"),
                    "is_current": bool(address.get("is_current")),
                }
                grouped[ip] = entry
            mac = str(address.get("mac") or "")
            interface = str(address.get("interface") or "")
            if mac and mac not in entry["macs"]:
                entry["macs"].append(mac)
            if interface and interface not in entry["interfaces"]:
                entry["interfaces"].append(interface)
            if str(address.get("first_seen") or "") < str(entry["first_seen"] or ""):
                entry["first_seen"] = address.get("first_seen")
            if str(address.get("last_seen") or "") > str(entry["last_seen"] or ""):
                entry["last_seen"] = address.get("last_seen")
            entry["is_current"] = entry["is_current"] or bool(address.get("is_current"))
        return sorted(grouped.values(), key=lambda item: str(item.get("last_seen") or ""), reverse=True)

    def update_device(self, device_id: str, patch: Mapping[str, Any]) -> dict[str, Any] | None:
        fields: list[str] = []
        values: list[Any] = []
        events: list[tuple[str, str]] = []
        if "display_name" in patch:
            name = str(patch.get("display_name") or "").strip()
            if len(name) > 80:
                raise ValueError("设备名称不能超过 80 个字符")
            fields.append("display_name = ?")
            values.append(name)
            events.append(("renamed", name or "（已清空名称）"))
        if "note" in patch:
            note = str(patch.get("note") or "").strip()
            if len(note) > 500:
                raise ValueError("备注不能超过 500 个字符")
            fields.append("note = ?")
            values.append(note)
            events.append(("note", "备注已更新"))
        if "favorite" in patch:
            favorite = 1 if patch.get("favorite") else 0
            fields.append("favorite = ?")
            values.append(favorite)
            events.append(("favorite", "已收藏" if favorite else "已取消收藏"))
        if not fields:
            return self.get_device(device_id)
        now_text = _now()
        fields.append("updated_at = ?")
        values.append(now_text)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT device_id FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if existing is None:
                return None
            values.append(device_id)
            connection.execute(
                f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?",
                tuple(values),
            )
            for kind, detail in events:
                self._event(connection, device_id, kind, detail, "", now_text)
        return self.get_device(device_id)
    # ---------------------------------------------------------- scan history
    def record_scan_task(
        self,
        snapshot: Mapping[str, Any],
        *,
        kind: str = "mac",
        custom_ranges: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        task_id = str(snapshot.get("job_id") or "").strip() or ("task_" + uuid.uuid4().hex)
        status = str(snapshot.get("status") or "completed")
        results = [dict(item) for item in (snapshot.get("results") or []) if isinstance(item, Mapping)]
        networks = [dict(item) for item in (snapshot.get("networks") or []) if isinstance(item, Mapping)]
        range_names = [str(item.get("scan_range") or "") for item in networks if item.get("scan_range")]
        complete = kind == "inventory" and status == "completed"
        summary = self.ingest_observations(
            results,
            task_id=task_id,
            complete=complete,
            networks=range_names,
        )
        started_at = str(snapshot.get("started_at") or _now())
        finished_at = str(snapshot.get("finished_at") or _now())
        row_values = (
            task_id,
            kind,
            status,
            started_at,
            finished_at,
            json.dumps(snapshot.get("selected_network_ids") or [], ensure_ascii=False),
            json.dumps(networks, ensure_ascii=False),
            json.dumps(snapshot.get("suffixes") or [], ensure_ascii=False),
            json.dumps(list(custom_ranges or []), ensure_ascii=False),
            int(snapshot.get("total_hosts") or 0),
            int(snapshot.get("probed_hosts") or 0),
            len(results),
            summary["new_devices"],
            summary["offline_devices"],
            summary["ip_changes"],
            len(results),
            json.dumps(snapshot.get("warnings") or [], ensure_ascii=False),
            str(snapshot.get("error") or ""),
            json.dumps(results, ensure_ascii=False),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO scan_tasks("
                "task_id, kind, status, started_at, finished_at, network_ids, "
                "networks, suffixes, custom_ranges, total_hosts, probed_hosts, "
                "discovered, new_devices, offline_devices, ip_changes, "
                "result_count, warnings, error, results"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "status = excluded.status, finished_at = excluded.finished_at, "
                "discovered = excluded.discovered, new_devices = excluded.new_devices, "
                "offline_devices = excluded.offline_devices, ip_changes = excluded.ip_changes, "
                "result_count = excluded.result_count, warnings = excluded.warnings, "
                "error = excluded.error, results = excluded.results",
                row_values,
            )
        return self.get_task(task_id) or {}

    def list_tasks(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        safe_limit = max(1, min(500, int(limit)))
        safe_offset = max(0, int(offset))
        with self._lock, self._connect() as connection:
            total = int(
                connection.execute("SELECT COUNT(*) FROM scan_tasks").fetchone()[0]
            )
            rows = connection.execute(
                "SELECT task_id, kind, status, started_at, finished_at, network_ids, "
                "networks, suffixes, custom_ranges, total_hosts, probed_hosts, "
                "discovered, new_devices, offline_devices, ip_changes, result_count, "
                "warnings, error FROM scan_tasks "
                "ORDER BY finished_at DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
        tasks = []
        for row in rows:
            item = dict(row)
            for key in ("network_ids", "networks", "suffixes", "custom_ranges", "warnings"):
                try:
                    item[key] = json.loads(item.get(key) or "[]")
                except (TypeError, ValueError):
                    item[key] = []
            tasks.append(item)
        return {"tasks": tasks, "total": total, "limit": safe_limit, "offset": safe_offset}

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scan_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        for key in ("network_ids", "networks", "suffixes", "custom_ranges", "warnings", "results"):
            try:
                item[key] = json.loads(item.get(key) or "[]")
            except (TypeError, ValueError):
                item[key] = []
        return item

    # ------------------------------------------------------------- MAC query
    def lookup_mac(self, query: str, mode: str = "auto") -> dict[str, Any]:
        compact = _compact(query)
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
        if mode == "full":
            clause = "REPLACE(a.mac, '-', '') = ?"
            parameter = compact
        elif mode == "prefix":
            clause = "REPLACE(a.mac, '-', '') LIKE ?"
            parameter = compact + "%"
        elif mode == "suffix":
            clause = "REPLACE(a.mac, '-', '') LIKE ?"
            parameter = "%" + compact
        else:
            clause = "REPLACE(a.mac, '-', '') LIKE ?"
            parameter = "%" + compact + "%"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT d.device_id, d.display_name, d.note, d.favorite, d.vendor, "
                "d.mac_current, d.ip_current, d.interface_current, d.network_current, "
                "d.status, d.status_state, d.last_seen, d.last_checked, d.random_mac, "
                "a.mac AS matched_mac, a.ip AS matched_ip, a.last_seen AS matched_seen "
                "FROM device_addresses a JOIN devices d ON d.device_id = a.device_id "
                f"WHERE {clause} ORDER BY a.last_seen DESC LIMIT 500",
                (parameter,),
            ).fetchall()
        settings = self.get_settings()
        stale_minutes = int(settings["stale_after_minutes"])
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            device_id = str(row["device_id"])
            entry = grouped.get(device_id)
            if entry is None:
                pseudo = {
                    "display_name": row["display_name"],
                    "vendor": row["vendor"],
                    "mac_current": row["mac_current"],
                }
                checked = _parse_time(row["last_checked"])
                status = _effective_status(row, stale_minutes)
                entry = {
                    "device_id": device_id,
                    "name": _device_label(pseudo),
                    "display_name": row["display_name"] or "",
                    "favorite": bool(row["favorite"]),
                    "vendor": row["vendor"] or "",
                    "vendor_known": bool(row["vendor"]),
                    "mac": row["mac_current"] or "",
                    "ip": row["ip_current"] or "",
                    "interface": row["interface_current"] or "",
                    "network_id": row["network_current"] or "",
                    "status": status,
                    "status_state": row["status_state"] or "",
                    "status_reason": _status_reason(status, str(row["status_state"] or ""), checked, stale_minutes),
                    "last_seen": row["last_seen"] or "",
                    "random_mac": bool(row["random_mac"]),
                    "matched_macs": [],
                }
                grouped[device_id] = entry
            if row["matched_mac"] and row["matched_mac"] not in entry["matched_macs"]:
                entry["matched_macs"].append(row["matched_mac"])
        matches = sorted(grouped.values(), key=lambda item: str(item.get("last_seen") or ""), reverse=True)
        vendor_hint = None
        if mode in {"full", "prefix"} and len(compact) >= 6:
            vendor_hint = {"prefix": compact[:6], "vendor": vendor_for_mac(compact[:6] + "000000")}
        return {
            "query": str(query),
            "mode": mode,
            "hex": compact,
            "vendor_hint": vendor_hint,
            "matches": matches,
            "count": len(matches),
        }

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        settings = self.get_settings()
        stale_minutes = int(settings["stale_after_minutes"])
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM devices").fetchall()
            last_task = connection.execute(
                "SELECT finished_at FROM scan_tasks ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
            scans_today = int(
                connection.execute(
                    "SELECT COUNT(*) FROM scan_tasks WHERE finished_at >= ?",
                    (datetime.now().strftime("%Y-%m-%d"),),
                ).fetchone()[0]
            )
        counts = {"online": 0, "offline": 0, "unknown": 0}
        favorites = 0
        networks: set[str] = set()
        for row in rows:
            status = _effective_status(row, stale_minutes)
            counts[status] = counts.get(status, 0) + 1
            if row["favorite"]:
                favorites += 1
            if row["network_current"]:
                networks.add(str(row["network_current"]))
        return {
            "total": len(rows),
            "online": counts["online"],
            "offline": counts["offline"],
            "unknown": counts["unknown"],
            "favorites": favorites,
            "networks": len(networks),
            "scans_today": scans_today,
            "last_scan_at": last_task["finished_at"] if last_task else "",
        }

    def recent_devices(self, limit: int = 6) -> list[dict[str, Any]]:
        result = self.list_devices(sort="last_seen", direction="desc", limit=limit)
        return result["devices"]

    def purge_history(self, older_than_days: int | None = None) -> int:
        settings = self.get_settings()
        days = int(older_than_days if older_than_days is not None else settings["history_retention_days"])
        cutoff = (datetime.now() - timedelta(days=max(1, days))).isoformat(timespec="seconds")
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM scan_tasks WHERE finished_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)


def _ip_sort_value(value: str) -> tuple[int, ...]:
    parts = str(value or "").split(".")
    if len(parts) != 4:
        return (999, 999, 999, 999)
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return (999, 999, 999, 999)