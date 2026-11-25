"""Network Locator V2 JSON API.

The legacy endpoints in :mod:`network_locator.server` are intentionally left
untouched. This module adds the V2 routes used by the new pages. It is imported
lazily from the request dispatcher so the package keeps its original import
graph and test surface.
"""

from __future__ import annotations

import inspect
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

from .core import (
    CommandError,
    ScanManager,
    discover_networks,
    max_configured_hosts,
    merge_custom_targets,
    network_target_key,
    network_target_payload,
    normalize_custom_ranges,
    normalize_network_ids,
    ping_statistics,
    probe_network_devices,
    read_dns_servers,
    select_network_targets,
)
from .oui import (
    is_virtual_vendor,
    lookup_vendor_prefixes,
    mac_kind,
    vendor_count,
    vendor_for_mac,
    vendor_from_query,
)
from .store import SCHEMA_VERSION, Store

MAX_BATCH_LOOKUPS = 100


class V2Error(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _query(handler: Any) -> dict[str, list[str]]:
    return parse_qs(urlsplit(handler.path).query, keep_blank_values=True)


def _one(values: Mapping[str, list[str]], key: str, default: str = "") -> str:
    items = values.get(key)
    return items[-1] if items else default


def _bounded_int(
    values: Mapping[str, list[str]],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = _one(values, key, "")
    try:
        value = int(raw) if raw != "" else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _store(handler: Any) -> Store:
    store = getattr(handler.server, "store", None)
    if store is None:
        raise V2Error(503, "数据存储尚未就绪")
    return store


def _manager(handler: Any) -> ScanManager:
    manager = getattr(handler.server, "scan_manager", None)
    if manager is None:
        raise V2Error(503, "扫描服务尚未就绪")
    return manager


def _bool_param(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _network_payloads(targets: Any) -> list[dict[str, Any]]:
    return [network_target_payload(target) for target in targets]


def _analysis(store: Store) -> dict[str, Any]:
    targets, warnings = discover_networks()
    payloads = _network_payloads(targets)
    store.record_network_snapshot(payloads)
    counts = store.network_counts()
    interfaces = []
    for payload in payloads:
        bucket = counts.get(payload["network_id"], {})
        payload["device_count"] = int(bucket.get("total", 0))
        payload["online_count"] = int(bucket.get("online", 0))
        interfaces.append(payload)
    return {
        "interfaces": interfaces,
        "warnings": warnings,
        "dns_servers": read_dns_servers(),
        "networks": [
            {
                "network_id": key,
                "total": value["total"],
                "online": value["online"],
                "offline": value["offline"],
                "unknown": value["unknown"],
            }
            for key, value in sorted(counts.items())
        ],
        "vendors": store.vendor_counts(12),
        "known_interfaces": store.list_interfaces(),
        "known_segments": store.list_segments(),
    }


def _summary(handler: Any) -> dict[str, Any]:
    store = _store(handler)
    targets, warnings = discover_networks()
    payloads = _network_payloads(targets)
    store.record_network_snapshot(payloads)
    by_network = store.network_counts()
    networks = []
    for payload in payloads:
        payload["device_count"] = int(by_network.get(payload["network_id"], {}).get("total", 0))
        networks.append(payload)
    settings = store.get_settings()
    return {
        "ok": True,
        "app": "network-locator",
        "stats": store.stats(),
        "recent": store.recent_devices(6),
        "networks": networks,
        "warnings": warnings,
        "settings": settings,
        "storage": store.storage_info(),
        "vendor_count": vendor_count(),
        "schema_version": SCHEMA_VERSION,
        "known_interfaces": store.list_interfaces(),
        "known_segments": store.list_segments(),
    }


def _list_devices(handler: Any, method: str) -> None:
    store = _store(handler)
    if method == "GET":
        values = _query(handler)
        result = store.list_devices(
            query=_one(values, "query"),
            status=_one(values, "status"),
            favorite=_bool_param(_one(values, "favorite")),
            sort=_one(values, "sort", "last_seen"),
            direction=_one(values, "direction", "desc"),
            limit=int(_one(values, "limit", "500") or 500),
            offset=int(_one(values, "offset", "0") or 0),
        )
        handler._send_json(
            200,
            {
                "ok": True,
                **result,
                "stats": store.stats(),
                "settings": store.get_settings(),
            },
            head_only=handler.command == "HEAD",
        )
        return
    raise V2Error(405, "method not allowed")


def _device_detail(handler: Any, method: str, device_id: str) -> None:
    store = _store(handler)
    if method in {"GET", "HEAD"}:
        device = store.get_device(device_id)
        if device is None:
            raise V2Error(404, "设备不存在")
        handler._send_json(
            200,
            {"ok": True, "device": device},
            head_only=method == "HEAD",
        )
        return
    if method == "PATCH":
        body = handler._read_json_body()
        allowed = {
            key: body[key]
            for key in ("display_name", "note", "favorite")
            if key in body
        }
        try:
            device = store.update_device(device_id, allowed)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        if device is None:
            raise V2Error(404, "设备不存在")
        handler._send_json(200, {"ok": True, "device": device})
        return
    raise V2Error(405, "method not allowed")


def _default_interface_ids(
    targets: list[Any],
    network_ids: list[str] | None,
    default_interface: str,
) -> tuple[list[str] | None, list[str]]:
    interface = str(default_interface or "").strip()
    if network_ids is not None or not interface:
        return network_ids, []
    matching = [
        network_target_key(item) for item in targets if item.interface == interface
    ]
    if matching:
        return matching, []
    return None, [f"默认网卡 {interface} 当前不可用，已自动选择所有网段"]


def run_inventory_scan(
    store: Store,
    manager: ScanManager,
    lock: Any,
    *,
    network_ids: list[str] | None = None,
    custom_ranges: list[str] | None = None,
    kind: str = "inventory",
) -> dict[str, Any]:
    """Run one inventory scan and persist its task without going through HTTP."""

    if lock is None:
        raise V2Error(503, "扫描锁不可用")
    if not lock.acquire(blocking=False):
        raise V2Error(409, "设备扫描正在进行中")
    try:
        if manager.status().get("running"):
            raise V2Error(409, "另一个扫描任务正在进行中")
        targets, warnings = discover_networks()
        settings = store.get_settings()
        network_ids, default_warnings = _default_interface_ids(
            targets, network_ids, str(settings.get("default_interface") or "")
        )
        warnings = warnings + default_warnings
        targets, missing = select_network_targets(targets, network_ids)
        targets = merge_custom_targets(targets, custom_ranges or [])
        if missing:
            warnings = warnings + ["所选网段当前不可用：" + "、".join(missing)]
        if not targets:
            raise V2Error(409, "当前没有可扫描的网段")
        started_at = _now()
        devices, probe_warnings = probe_network_devices(targets)
        finished_at = _now()
        total = sum(target.host_count for target in targets)
        network_payloads = _network_payloads(targets)
        store.record_network_snapshot(network_payloads)
        snapshot = {
            "job_id": "inv_" + uuid.uuid4().hex,
            "status": "completed",
            "started_at": started_at,
            "finished_at": finished_at,
            "networks": network_payloads,
            "selected_network_ids": [
                payload["network_id"] for payload in network_payloads
            ],
            "suffixes": [],
            "custom_ranges": custom_ranges or [],
            "total_hosts": total,
            "probed_hosts": total,
            "results": devices,
            "warnings": warnings + probe_warnings,
            "error": "",
        }
        task = store.record_scan_task(
            snapshot, kind=kind, custom_ranges=custom_ranges or []
        )
        result = store.list_devices(limit=500)
        return {
            "ok": True,
            "devices": result["devices"],
            "total": result["total"],
            "task": task,
            "warnings": warnings + probe_warnings,
            "stats": store.stats(),
        }
    finally:
        lock.release()


def _inventory_scan(handler: Any) -> None:
    store = _store(handler)
    manager = _manager(handler)
    body = handler._read_json_body()
    try:
        network_ids = normalize_network_ids(body.get("network_ids"))
        custom_ranges = normalize_custom_ranges(body.get("custom_ranges"))
    except ValueError as exc:
        raise V2Error(400, str(exc)) from exc
    lock = getattr(handler.server, "device_scan_lock", None)
    handler._send_json(
        200,
        run_inventory_scan(
            store,
            manager,
            lock,
            network_ids=network_ids,
            custom_ranges=custom_ranges,
            kind="inventory",
        ),
    )


class AutoScanScheduler:
    """Run the persisted automatic inventory policy from the service process."""

    def __init__(
        self,
        store: Store,
        manager: ScanManager,
        lock: Any,
        *,
        runner: Any = None,
        clock: Any = None,
        check_interval_seconds: float = 5.0,
        logger: Any = None,
    ) -> None:
        self._store = store
        self._manager = manager
        self._lock = lock
        self._runner = runner or self._run_inventory
        self._clock = clock or time.monotonic
        self._check_interval = max(0.05, float(check_interval_seconds))
        self._logger = logger or (lambda message: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_monotonic: float | None = None
        self._signature: tuple[bool, int] | None = None
        self.last_run_at = ""
        self.last_error = ""

    def _run_inventory(self) -> dict[str, Any]:
        return run_inventory_scan(
            self._store,
            self._manager,
            self._lock,
            kind="auto",
        )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_monotonic = self._clock()
        self._signature = None
        self._thread = threading.Thread(
            target=self._loop,
            name="auto-scan-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._check_interval):
            self.poll_once()

    def poll_once(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else float(now)
        settings = self._store.get_settings()
        enabled = bool(settings.get("auto_scan_enabled"))
        interval = max(1, int(settings.get("auto_scan_interval_minutes") or 30)) * 60
        signature = (enabled, interval)
        if signature != self._signature:
            # Enabling the policy or changing its interval starts a fresh wait
            # instead of firing immediately because the process has run longer
            # than the new interval.
            self._signature = signature
            self._last_monotonic = current
            return False
        if not enabled:
            return False
        if self._last_monotonic is None:
            self._last_monotonic = current
            return False
        if current - self._last_monotonic < interval:
            return False
        if self._manager.status().get("running"):
            return False
        try:
            self._runner()
        except V2Error as exc:
            if exc.status == 409:
                return False
            self.last_error = str(exc)
            self._last_monotonic = self._clock()
            self._logger(f"automatic scan failed: {exc}")
            return False
        except Exception as exc:
            self.last_error = str(exc)
            self._last_monotonic = self._clock()
            self._logger(f"automatic scan failed: {exc}")
            return False
        self.last_error = ""
        self.last_run_at = _now()
        self._last_monotonic = self._clock()
        self._logger("automatic scan completed")
        return True

    def status(self) -> dict[str, Any]:
        settings = self._store.get_settings()
        enabled = bool(settings.get("auto_scan_enabled"))
        interval = max(1, int(settings.get("auto_scan_interval_minutes") or 30)) * 60
        remaining = 0
        if enabled and self._last_monotonic is not None:
            remaining = max(0, int(interval - (self._clock() - self._last_monotonic)))
        return {
            "managed": True,
            "thread_alive": bool(self._thread is not None and self._thread.is_alive()),
            "enabled": enabled,
            "interval_minutes": interval // 60,
            "seconds_until_next": remaining,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
        }


def _networks_route(handler: Any, method: str) -> None:
    store = _store(handler)
    if method not in {"GET", "HEAD"}:
        raise V2Error(405, "method not allowed")
    targets, warnings = discover_networks()
    payloads = _network_payloads(targets)
    store.record_network_snapshot(payloads)
    handler._send_json(
        200,
        {
            "ok": True,
            "networks": payloads,
            "warnings": warnings,
            "max_hosts": max_configured_hosts(),
            "settings": store.get_settings(),
        },
        head_only=method == "HEAD",
    )


def _scan_start_route(handler: Any) -> None:
    body = handler._read_json_body()
    if "scan_all" in body:
        scan_all = bool(body.get("scan_all"))
    else:
        scan_all = not (body.get("suffixes") or body.get("suffix"))
    custom_only = bool(body.get("custom_only"))
    try:
        raw_network_ids = body.get("network_ids")
        if custom_only and raw_network_ids == []:
            network_ids = None
        else:
            network_ids = normalize_network_ids(raw_network_ids)
        custom_ranges = normalize_custom_ranges(body.get("custom_ranges"))
    except ValueError as exc:
        raise V2Error(400, str(exc)) from exc
    if custom_only and not custom_ranges:
        raise V2Error(400, "自定义范围不能为空")
    manager = _manager(handler)
    store = _store(handler)
    default_interface = ""
    if network_ids is None and not custom_only:
        default_interface = str(store.get_settings().get("default_interface") or "").strip()
    lock = getattr(handler.server, "device_scan_lock", None)
    if lock is None:
        raise V2Error(503, "扫描锁不可用")
    if not lock.acquire(blocking=False):
        raise V2Error(409, "另一个扫描任务正在进行中")
    try:
        if manager.status().get("running"):
            raise V2Error(409, "另一个扫描任务正在进行中")
        started = manager.start(
            [],
            network_ids,
            custom_ranges,
            custom_only,
            scan_all=scan_all,
            default_interface=default_interface,
        )
        actual = manager.status()
        handler._send_json(
            202 if started else 200,
            {
                "ok": True,
                "started": started,
                "running": bool(actual.get("running")),
                "status": actual.get("status"),
                "job_id": actual.get("job_id", ""),
                "paused": bool(actual.get("paused")),
                "scan_all": bool(actual.get("scan_all")),
                "kind": actual.get("kind", "mac"),
                "selected_network_ids": actual.get("selected_network_ids", []),
                "custom_ranges": actual.get("custom_ranges", custom_ranges),
                "custom_only": bool(actual.get("custom_only")),
            },
        )
    except ValueError as exc:
        raise V2Error(400, str(exc)) from exc
    finally:
        lock.release()


def _scan_status_route(handler: Any, method: str) -> None:
    if method not in {"GET", "HEAD"}:
        raise V2Error(405, "method not allowed")
    handler._send_json(
        200,
        {"ok": True, **_manager(handler).status()},
        head_only=method == "HEAD",
    )


def _scan_control_route(handler: Any, action: str) -> None:
    handler._read_json_body()
    manager = _manager(handler)
    if action == "pause":
        changed = manager.pause()
    elif action == "resume":
        changed = manager.resume()
    else:
        changed = manager.stop()
    status = manager.status()
    handler._send_json(
        200,
        {
            "ok": True,
            "changed": changed,
            "running": bool(status.get("running")),
            "paused": bool(status.get("paused")),
            "stopping": bool(status.get("stopping")),
            "status": status.get("status"),
            "job_id": status.get("job_id", ""),
            "progress_percent": status.get("progress_percent", 0),
        },
    )


def _live_mac_matches(handler: Any, query: str, mode: str) -> list[dict[str, Any]]:
    try:
        status = _manager(handler).status()
    except Exception:
        return []
    compact = "".join(
        character for character in str(query or "").upper()
        if character in "0123456789ABCDEF"
    )
    vendor_prefixes: list[str] = []
    if mode == "vendor":
        vendor = vendor_from_query(query)
        vendor_prefixes = list(vendor["prefixes"]) if vendor else []
        compact = ""
    if not compact and not vendor_prefixes:
        return []
    matches: list[dict[str, Any]] = []
    for item in status.get("results") or []:
        mac = str(item.get("mac") or "").replace("-", "")
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
        if mode == "vendor" and not any(
            mac.startswith(prefix) for prefix in vendor_prefixes
        ):
            continue
        vendor = vendor_for_mac(mac)
        mac_type = mac_kind(mac)
        matches.append(
            {
                "device_id": "",
                "name": "扫描结果 " + mac[-4:],
                "display_name": "",
                "favorite": False,
                "vendor": vendor,
                "vendor_known": bool(vendor),
                "mac": str(item.get("mac") or ""),
                "ip": str(item.get("ip") or ""),
                "interface": str(item.get("interface") or ""),
                "network_id": str(item.get("scan_range") or ""),
                "status": "online"
                if str(item.get("state") or "").upper() in {"LOCAL", "REACHABLE"}
                else "unknown",
                "status_state": str(item.get("state") or ""),
                "status_reason": "来自当前扫描结果，尚未写入设备档案",
                "status_reason_code": "live_not_persisted",
                "status_reason_args": [],
                "last_seen": status.get("finished_at") or status.get("started_at") or "",
                "random_mac": mac_type == "local",
                "mac_type": mac_type,
                "virtual_adapter": is_virtual_vendor(vendor),
                "matched_macs": [str(item.get("mac") or "")],
                "live": True,
            }
        )
    return matches


def _mac_lookup(handler: Any, method: str) -> None:
    store = _store(handler)
    if method == "GET":
        values = _query(handler)
        query = _one(values, "q") or _one(values, "query")
        mode = _one(values, "mode", "auto")
        try:
            limit = max(1, min(int(_one(values, "limit", "50") or 50), 200))
        except ValueError:
            limit = 50
        try:
            offset = max(0, int(_one(values, "offset", "0") or 0))
        except ValueError:
            offset = 0
        try:
            result = store.lookup_mac(query, mode, limit, offset)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        live = _live_mac_matches(handler, query, result["mode"]) if offset == 0 else []
        if live:
            known = {item["mac"].replace("-", "") for item in result["matches"]}
            added = [
                item for item in live if item["mac"].replace("-", "") not in known
            ]
            result["matches"].extend(added)
            result["count"] = len(result["matches"])
            if added:
                result["total"] = int(result.get("total") or 0) + len(added)
                result["has_more"] = offset + result["count"] < result["total"]
        result["input_kind"] = result["mode"]
        result["vendor_prefixes"] = (
            lookup_vendor_prefixes(result["hex"]) if result.get("hex") else []
        )
        handler._send_json(200, {"ok": True, **result}, head_only=handler.command == "HEAD")
        return
    if method == "POST":
        body = handler._read_json_body()
        raw_queries = body.get("queries")
        if raw_queries is None:
            raw_queries = [body.get("query") or ""]
        if not isinstance(raw_queries, list) or not raw_queries:
            raise V2Error(400, "请输入至少一个 MAC 查询")
        if len(raw_queries) > MAX_BATCH_LOOKUPS:
            raise V2Error(400, f"一次最多查询 {MAX_BATCH_LOOKUPS} 个 MAC")
        try:
            limit = max(1, min(int(body.get("limit") or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(body.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        results = []
        for query in raw_queries:
            text = str(query or "").strip()
            if not text:
                continue
            try:
                result = store.lookup_mac(text, "auto", limit, offset)
            except ValueError as exc:
                results.append(
                    {
                        "query": text,
                        "error": str(exc),
                        "matches": [],
                        "count": 0,
                        "total": 0,
                        "limit": limit,
                        "offset": offset,
                        "has_more": False,
                        "mode": "",
                        "hex": "",
                    }
                )
                continue
            live = _live_mac_matches(handler, text, result["mode"]) if offset == 0 else []
            if live:
                known = {item["mac"].replace("-", "") for item in result["matches"]}
                added = [
                    item for item in live if item["mac"].replace("-", "") not in known
                ]
                result["matches"].extend(added)
                result["count"] = len(result["matches"])
                if added:
                    result["total"] = int(result.get("total") or 0) + len(added)
                    result["has_more"] = offset + result["count"] < result["total"]
            result["input_kind"] = result["mode"]
            result["vendor_prefixes"] = (
                lookup_vendor_prefixes(result["hex"]) if result.get("hex") else []
            )
            results.append(result)
        handler._send_json(200, {"ok": True, "results": results})
        return
    raise V2Error(405, "method not allowed")


def _analysis_route(handler: Any, method: str) -> None:
    store = _store(handler)
    if method in {"GET", "HEAD"}:
        handler._send_json(
            200,
            {
                "ok": True,
                **_analysis(store),
                "stats": store.stats(),
                "settings": store.get_settings(),
                "storage": store.storage_info(),
            },
            head_only=method == "HEAD",
        )
        return
    if method == "POST":
        body = handler._read_json_body()
        try:
            count = int(body.get("count") or 4)
        except (TypeError, ValueError) as exc:
            raise V2Error(400, "Ping 次数必须是 1 到 20 之间的整数") from exc
        count = max(1, min(20, count))
        host = str(body.get("host") or "").strip()
        interface = str(body.get("interface") or "").strip()
        want_gateway = bool(body.get("gateway"))
        if not host and not want_gateway:
            raise V2Error(400, "请输入要测试的 IP 或主机名")
        if want_gateway:
            targets, warnings = discover_networks()
            target = None
            for candidate in targets:
                if interface and candidate.interface != interface:
                    continue
                if candidate.gateway:
                    target = candidate
                    break
            if target is None:
                raise V2Error(409, "没有可用的默认网关")
            host = target.gateway
        try:
            stats = ping_statistics(host, count=count)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        except CommandError as exc:
            raise V2Error(503, str(exc)) from exc
        handler._send_json(200, {"ok": True, "measured_at": _now(), **stats})
        return
    raise V2Error(405, "method not allowed")


def _scans_route(handler: Any, method: str, parts: list[str]) -> None:
    store = _store(handler)
    if len(parts) == 2 and method in {"GET", "HEAD"}:
        values = _query(handler)
        result = store.list_tasks(
            limit=_bounded_int(values, "limit", 50, 1, 200),
            offset=_bounded_int(values, "offset", 0, 0, 10_000_000),
        )
        handler._send_json(200, {"ok": True, **result}, head_only=method == "HEAD")
        return
    if len(parts) == 3 and parts[2] == "purge" and method == "POST":
        body = handler._read_json_body()
        days = body.get("older_than_days")
        removed = store.purge_history(int(days) if days is not None else None)
        handler._send_json(200, {"ok": True, "removed": removed})
        return
    if len(parts) == 3 and method in {"GET", "HEAD"}:
        values = _query(handler)
        task = store.get_task(
            parts[2],
            result_limit=_bounded_int(values, "result_limit", 50, 1, 500),
            result_offset=_bounded_int(values, "result_offset", 0, 0, 10_000_000),
            event_limit=_bounded_int(values, "event_limit", 50, 1, 200),
            event_offset=_bounded_int(values, "event_offset", 0, 0, 10_000_000),
        )
        if task is None:
            raise V2Error(404, "扫描任务不存在")
        handler._send_json(200, {"ok": True, "task": task}, head_only=method == "HEAD")
        return
    raise V2Error(404, "not found")


def _automation_status(handler: Any) -> dict[str, Any]:
    scheduler = getattr(handler.server, "auto_scan_scheduler", None)
    if scheduler is None:
        return {
            "managed": False,
            "enabled": False,
            "interval_minutes": 0,
            "seconds_until_next": 0,
            "last_run_at": "",
            "last_error": "",
        }
    return scheduler.status()


def _settings_payload(handler: Any, store: Store) -> dict[str, Any]:
    return {
        "settings": store.get_settings(),
        "storage": store.storage_info(),
        "automation": _automation_status(handler),
        "vendor_count": vendor_count(),
        "schema_version": SCHEMA_VERSION,
        "capabilities": [
            "store/sqlite",
            "devices",
            "scan-history",
            "mac-lookup",
            "network-analysis",
            "custom-ranges",
            "pause-resume",
            "network-scan",
            "storage-migration",
            "auto-scan-service",
        ],
    }


def _settings_route(handler: Any, method: str, parts: list[str]) -> None:
    store = _store(handler)
    if len(parts) == 3 and parts[2] == "storage":
        if method != "POST":
            raise V2Error(405, "method not allowed")
        body = handler._read_json_body()
        manager = _manager(handler)
        if manager.status().get("running"):
            raise V2Error(409, "另一个扫描任务正在进行中")
        lock = getattr(handler.server, "device_scan_lock", None)
        acquired = False
        try:
            if lock is not None:
                acquired = lock.acquire(blocking=False)
                if not acquired:
                    raise V2Error(409, "另一个扫描任务正在进行中")
                if manager.status().get("running"):
                    raise V2Error(409, "另一个扫描任务正在进行中")
            try:
                storage = store.relocate_storage(body.get("directory"))
            except ValueError as exc:
                raise V2Error(400, str(exc)) from exc
            handler._send_json(
                200,
                {
                    "ok": True,
                    "storage": storage,
                    "settings": store.get_settings(),
                    "automation": _automation_status(handler),
                },
            )
        finally:
            if acquired:
                lock.release()
        return
    if len(parts) != 2:
        raise V2Error(404, "not found")
    if method in {"GET", "HEAD"}:
        handler._send_json(
            200,
            {"ok": True, **_settings_payload(handler, store)},
            head_only=method == "HEAD",
        )
        return
    if method in {"PATCH", "POST"}:
        body = handler._read_json_body()
        try:
            settings = store.update_settings(body)
        except ValueError as exc:
            raise V2Error(400, str(exc)) from exc
        handler._send_json(
            200,
            {
                "ok": True,
                "settings": settings,
                "storage": store.storage_info(),
                "automation": _automation_status(handler),
            },
        )
        return
    raise V2Error(405, "method not allowed")


def handle_v2(handler: Any, method: str, parts: list[str]) -> bool:
    """Handle a V2 request. Return False when the path is not a V2 route."""

    if not parts or parts[0] != "v2":
        return False
    try:
        if parts == ["v2", "summary"]:
            if method not in {"GET", "HEAD"}:
                raise V2Error(405, "method not allowed")
            payload = _summary(handler)
            handler._send_json(200, payload, head_only=method == "HEAD")
            return True
        if parts == ["v2", "networks"]:
            _networks_route(handler, method)
            return True
        if parts == ["v2", "devices"]:
            _list_devices(handler, method)
            return True
        if parts == ["v2", "scan", "start"] and method == "POST":
            _scan_start_route(handler)
            return True
        if parts == ["v2", "scan", "status"]:
            _scan_status_route(handler, method)
            return True
        if parts in (["v2", "scan", "pause"], ["v2", "scan", "resume"], ["v2", "scan", "stop"]):
            if method != "POST":
                raise V2Error(405, "method not allowed")
            _scan_control_route(handler, parts[2])
            return True
        if parts == ["v2", "devices", "scan"] and method == "POST":
            _inventory_scan(handler)
            return True
        if len(parts) == 3 and parts[:2] == ["v2", "devices"]:
            _device_detail(handler, method, parts[2])
            return True
        if parts in (["v2", "mac", "lookup"], ["v2", "mac"]):
            _mac_lookup(handler, method)
            return True
        if parts in (["v2", "analysis"], ["v2", "analysis", "ping"]):
            _analysis_route(handler, method)
            return True
        if parts[:2] == ["v2", "scans"]:
            _scans_route(handler, method, parts)
            return True
        if parts[:2] == ["v2", "settings"]:
            _settings_route(handler, method, parts)
            return True
        raise V2Error(404, "not found")
    except V2Error as exc:
        handler._send_json(
            exc.status,
            {"ok": False, "app": "network-locator", "error": str(exc)},
            head_only=method == "HEAD",
        )
        return True
    except (BrokenPipeError, ConnectionResetError):
        return True
    except Exception as exc:  # pragma: no cover - defensive boundary
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        handler._send_json(
            500,
            {"ok": False, "app": "network-locator", "error": "internal server error"},
            head_only=method == "HEAD",
        )
        return True
